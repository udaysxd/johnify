from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Set, Tuple
from pathlib import Path
import time
import os
import json
import subprocess
import random
import threading
from collections import deque
from PIL import Image, ImageDraw, ImageFont, ImageOps
import google.generativeai as genai
import logging
from sqlalchemy import text
from .gcs_utils import maybe_upload_and_url
from .auth.models import User as AuthUser
from .auth.security import get_current_user
from .database import Session

# Mobile Lites (mlites) router
router = APIRouter(prefix="/api/mlites", tags=["mlites"])

# Logger
logger = logging.getLogger("mlites")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] mlites: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Voice pools per language for Google Cloud TTS
# We will randomly choose one voice for the user's preferred language at synthesis time
# Keys are normalized language names from language_master.lang (lowercased)
VOICE_POOLS: Dict[str, List[Dict[str, str]]] = {
    # English variants
    "english": [
        {"language_code": "en-US", "name": "en-US-Standard-B"},
        {"language_code": "en-GB", "name": "en-GB-Standard-N"},
        {"language_code": "en-GB", "name": "en-GB-News-M"},
        {"language_code": "en-AU", "name": "en-AU-Standard-B"},
        {"language_code": "en-GB", "name": "en-GB-Standard-O"},
        {"language_code": "en-GB", "name": "en-GB-Standard-N"},
        {"language_code": "en-US", "name": "en-US-Standard-D"},
        {"language_code": "en-US", "name": "en-US-Standard-E"},
        {"language_code": "en-US", "name": "en-US-Standard-F"},
        {"language_code": "en-US", "name": "en-US-Standard-H"},
        {"language_code": "en-GB", "name": "en-GB-Standard-D"},
        {"language_code": "en-GB", "name": "en-GB-Standard-B"},
        {"language_code": "en-GB", "name": "en-AU-Standard-D"},   
        ],
    # French (France)
    "french": [
        {"language_code": "fr-FR", "name": "fr-FR-Standard-F"},
        {"language_code": "fr-FR", "name": "fr-FR-Standard-G"},
    ],
    # Hindi (India)
    "hindi": [
        {"language_code": "hi-IN", "name": "hi-IN-Standard-E"},
        {"language_code": "hi-IN", "name": "hi-IN-Standard-C"},
    ],
    # Italian (Italy)
    "italian": [
        {"language_code": "it-IT", "name": "it-IT-Standard-F"},
        {"language_code": "it-IT", "name": "it-IT-Standard-E"},
    ],
    # Spanish (Spain)
    "spanish": [
        {"language_code": "es-ES", "name": "es-ES-Standard-F"},
        {"language_code": "es-ES", "name": "es-ES-Standard-G"},
    ],
}

# Global concurrency controls for mlites
_TTS_MAX = int(os.getenv("TTS_MAX_CONCURRENCY", "3") or "3")
_GEM_MAX = int(os.getenv("GEMINI_MAX_CONCURRENCY", "2") or "2")
_TTS_SEM = threading.BoundedSemaphore(max(1, _TTS_MAX))
_GEM_SEM = threading.BoundedSemaphore(max(1, _GEM_MAX))

# Background opacity control (0.0 - 1.0)
try:
    _MLITES_BG_OPACITY = float(os.getenv("MLITES_BG_OPACITY", "0.2") or "0.2")
except Exception:
    _MLITES_BG_OPACITY = 0.2
_MLITES_BG_OPACITY = max(0.0, min(1.0, _MLITES_BG_OPACITY))

def _sleep_backoff(attempt: int, base: float = 0.5, factor: float = 2.0, cap: float = 8.0, jitter: float = 0.25) -> None:
    delay = min(cap, base * (factor ** (attempt - 1)))
    jitter_amt = delay * jitter
    time.sleep(max(0.0, delay + random.uniform(-jitter_amt, jitter_amt)))

"""Gemini rate limiter (requests per 60s). Primary and two fallbacks have distinct RPMs."""
_GEM_PRIMARY_MODEL = os.getenv("GEMINI_PRIMARY_MODEL", "models/gemini-2.5-flash-lite")
_GEM_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "models/gemini-2.0-flash-lite")
_GEM_FALLBACK2_MODEL = os.getenv("GEMINI_FALLBACK2_MODEL", "models/gemini-2.0-flash")
_GEM_RPM = int(os.getenv("GEMINI_RPM", "15") or "15")  # primary default 15 rpm
_GEM_FALLBACK_RPM = int(os.getenv("GEMINI_FALLBACK_RPM", "30") or "30")
_GEM_FALLBACK2_RPM = int(os.getenv("GEMINI_FALLBACK2_RPM", "15") or "15")
_GEM_WINDOW_SEC = 60.0

# per-model sliding window state
_GEM_TIMES_PRIMARY = deque()  # type: ignore[var-annotated]
_GEM_TIMES_FALLBACK = deque()  # type: ignore[var-annotated]
_GEM_TIMES_FALLBACK2 = deque()  # type: ignore[var-annotated]
_GEM_TIMES_LOCK = threading.Lock()

def _gemini_acquire_slot_for(model_name: str):
    if model_name == _GEM_FALLBACK_MODEL:
        rpm = _GEM_FALLBACK_RPM
        times = _GEM_TIMES_FALLBACK
    elif model_name == _GEM_FALLBACK2_MODEL:
        rpm = _GEM_FALLBACK2_RPM
        times = _GEM_TIMES_FALLBACK2
    else:
        rpm = _GEM_RPM
        times = _GEM_TIMES_PRIMARY
    while True:
        now = time.time()
        with _GEM_TIMES_LOCK:
            while times and (now - times[0]) >= _GEM_WINDOW_SEC:
                times.popleft()
            if len(times) < max(1, rpm):
                times.append(now)
                return
            oldest = times[0]
            wait_for = max(0.0, _GEM_WINDOW_SEC - (now - oldest))
        time.sleep(min(wait_for + random.uniform(0.0, 0.1), 2.0))

# SSE broker
try:
    from .services.sse_broker import broker
except Exception:
    from .services.sse_broker import broker  # type: ignore

# ---- Helpers ----

def _get_generated_root() -> Path:
    """Return the unified generated root directory.
    - production: /tmp/generated
    - dev/local: <repo_root>/generated
    """
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    IS_PRODUCTION = ENVIRONMENT == "production"
    if IS_PRODUCTION:
        base_root = Path("/tmp")
    else:
        # repo root = backend/app/../../
        base_root = Path(__file__).resolve().parent.parent.parent
    return (base_root / "generated").resolve()

def _sanitize_filename(filename: str) -> str:
    import re, unicodedata
    filename = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
    filename = re.sub(r'[\\/*?:"<>| ]', '_', filename)
    filename = re.sub(r'_+', '_', filename).strip('_')
    return filename or "mlite"


def _ensure_dirs(base: Path) -> Dict[str, Path]:
    base.mkdir(parents=True, exist_ok=True)
    (base / "images").mkdir(exist_ok=True)
    (base / "audio").mkdir(exist_ok=True)
    return {"images": base / "images", "audio": base / "audio"}


def _pick_tts_voice_for_user(user_id: Optional[int]) -> Dict[str, str]:
    """Pick a random TTS voice based on the user's preferred language.
    Falls back to English if none is set or not recognized.
    Returns a dict: {"language_code": str, "name": str}
    """
    # Default to English pool
    pool_key = "english"
    if user_id is not None:
        try:
            db = Session()
            try:
                row = db.execute(text(
                    """
                    SELECT
                      COALESCE(lm.lang_code, lm."lang-code") AS lang_code,
                      LOWER(lm.lang) AS lang
                    FROM public.user_preferences up
                    JOIN language_master lm ON lm.id = up.language_id
                    WHERE up.user_id = :uid
                    LIMIT 1
                    """
                ), {"uid": int(user_id)}).mappings().first()
                code = (row.get("lang_code") or "").strip() if row else ""
                if code:
                    pool_key = _language_key_from_code(code)
                elif row and (row.get("lang") or "").strip():
                    # Fallback to name prefix if code missing
                    lang = str(row.get("lang") or "").strip().lower()
                    if lang.startswith("english"): pool_key = "english"
                    elif lang.startswith("french"): pool_key = "french"
                    elif lang.startswith("hindi"): pool_key = "hindi"
                    elif lang.startswith("italian"): pool_key = "italian"
                    elif lang.startswith("spanish"): pool_key = "spanish"
            finally:
                try:
                    db.close()
                except Exception:
                    pass
        except Exception:
            pass
    pool = VOICE_POOLS.get(pool_key) or VOICE_POOLS["english"]
    try:
        return random.choice(pool)
    except Exception:
        return {"language_code": "en-US", "name": "en-US-Standard-B"}


def _get_user_language_key(user_id: Optional[int]) -> str:
    """Return normalized language key for the user ('english','hindi','french','italian','spanish'). Default 'english'."""
    key = "english"
    if user_id is None:
        return key
    try:
        db = Session()
        try:
            row = db.execute(text(
                """
                SELECT
                  lm.lang_code AS lang_code,
                  LOWER(lm.lang) AS lang
                FROM public.user_preferences up
                JOIN public.language_master lm ON lm.id = up.language_id
                WHERE up.user_id = :uid
                LIMIT 1
                """
            ), {"uid": int(user_id)}).mappings().first()
            logger.info(f"[mlites] _get_user_language_key: user_id={user_id} row={dict(row) if row else None}")
            code = (row.get("lang_code") or "").strip() if row else ""
            if code:
                key = _language_key_from_code(code)
            elif row and (row.get("lang") or "").strip():
                lang = str(row.get("lang") or "").strip().lower()
                if lang.startswith("english"): key = "english"
                elif lang.startswith("french"): key = "french"
                elif lang.startswith("hindi"): key = "hindi"
                elif lang.startswith("italian"): key = "italian"
                elif lang.startswith("spanish"): key = "spanish"
            else:
                # Hard fallback: fetch language_id first then resolve code
                try:
                    rid = db.execute(text(
                        "SELECT language_id FROM public.user_preferences WHERE user_id = :uid LIMIT 1"
                    ), {"uid": int(user_id)}).mappings().first()
                    logger.info(f"[mlites] _get_user_language_key: fallback prefs row={dict(rid) if rid else None}")
                    if rid and rid.get("language_id") is not None:
                        rcode = db.execute(text(
                            "SELECT lang_code AS lang_code FROM public.language_master WHERE id = :id LIMIT 1"
                        ), {"id": int(rid.get("language_id"))}).mappings().first()
                        logger.info(f"[mlites] _get_user_language_key: fallback code row={dict(rcode) if rcode else None}")
                        c2 = (rcode.get("lang_code") or "").strip() if rcode else ""
                        if c2:
                            key = _language_key_from_code(c2)
                except Exception:
                    pass
        finally:
            try:
                db.close()
            except Exception:
                pass
    except Exception:
        pass
    return key


def _language_key_from_code(code: str) -> str:
    c = (code or "").strip().lower()
    if not c:
        return "english"
    # Handle common BCP-47 forms
    if c == "hi" or c.startswith("hi-"):
        return "hindi"
    if c == "fr" or c.startswith("fr-"):
        return "french"
    if c == "it" or c.startswith("it-"):
        return "italian"
    if c == "es" or c.startswith("es-"):
        return "spanish"
    # default
    return "english"


def _maybe_translate_narrations(narr: List[str], target_key: str) -> List[str]:
    """Translate the narration array to the target language using Gemini if target_key != 'english'.
    Returns the original list on any failure.
    """
    if not narr or target_key in (None, "", "english"):
        return narr
    try:
        # Map key to human language name for prompt
        lang_name = {
            "french": "French",
            "hindi": "Hindi",
            "italian": "Italian",
            "spanish": "Spanish",
        }.get(target_key)
        if not lang_name:
            return narr
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return narr
        genai.configure(api_key=api_key)
        model_name = os.getenv("GEMINI_PRIMARY_MODEL", "models/gemini-2.5-flash-lite")
        model = genai.GenerativeModel(model_name)
        import json as _json
        extra = ""
        if target_key == "hindi":
            extra = "Use Devanagari script (हिंदी लिपि), not transliteration."
        prompt = (
            "Translate the following JSON array of narration strings to " + lang_name + ".\n"
            "- Return ONLY a JSON array of strings with the SAME length and order.\n"
            "- Keep the meaning natural and educational.\n"
            "- Do not include any extra text.\n" + extra + "\n"
        )
        text_in = _json.dumps(narr, ensure_ascii=False)
        resp = model.generate_content(prompt + "\n\nArray:\n" + text_in)
        out_text = resp.text or ""
        try:
            # try direct parse
            arr = _json.loads(out_text)
        except Exception:
            import re as _re
            m = _re.search(r"\[[\s\S]*\]", out_text)
            if not m:
                arr = None
            else:
                try:
                    arr = _json.loads(m.group(0))
                except Exception:
                    arr = None
        if isinstance(arr, list) and len(arr) == len(narr):
            # normalize to strings
            return [str(x) for x in arr]
        # Fallback: translate item-by-item
        try:
            out_items: List[str] = []
            for s in narr:
                p = (
                    f"Translate the following sentence to {lang_name}. Return ONLY the translated sentence, no quotes, no extra text. "
                    + ("Use Devanagari script (हिंदी लिपि)." if target_key == "hindi" else "")
                )
                r = model.generate_content(p + "\n\n" + str(s))
                txt = (r.text or "").strip()
                # Trim wrapping quotes if any
                if len(txt) >= 2 and ((txt[0] == '"' and txt[-1] == '"') or (txt[0] == "'" and txt[-1] == "'")):
                    txt = txt[1:-1].strip()
                out_items.append(txt)
            if len(out_items) == len(narr):
                return out_items
        except Exception:
            pass
        return narr
    except Exception:
        return narr


def _enforce_translation(narr: List[str], target_key: str) -> List[str]:
    """Ensure the array is actually in target language. For Hindi, require Devanagari chars.
    For Romance languages (fr/es/it), if a line remains identical/ASCII-English looking, retry per-item.
    Returns the best-effort translated array (never raises).
    """
    try:
        if not narr or target_key in (None, "", "english"):
            return narr
        import re
        out = list(narr)
        # Helper to check Devanagari presence
        def has_devanagari(s: str) -> bool:
            return bool(re.search(r"[\u0900-\u097F]", s or ""))
        # If Hindi: make sure each line has Devanagari
        if target_key == "hindi":
            need_fix_idx = [i for i, s in enumerate(out) if not has_devanagari(str(s))]
            if need_fix_idx:
                fixed = _maybe_translate_narrations([out[i] for i in need_fix_idx], target_key)
                for j, i in enumerate(need_fix_idx):
                    out[i] = fixed[j] if j < len(fixed) else out[i]
        else:
            # For fr/es/it: if a line is unchanged ASCII and equals original English-ish, retry once
            def looks_english_ascii(s: str) -> bool:
                s2 = (s or "").strip()
                if not s2:
                    return False
                # No accented characters and primarily a-z letters
                return all(ord(ch) < 128 for ch in s2)
            need_fix_idx = [i for i, s in enumerate(out) if looks_english_ascii(str(s))]
            if need_fix_idx:
                fixed = _maybe_translate_narrations([out[i] for i in need_fix_idx], target_key)
                for j, i in enumerate(need_fix_idx):
                    out[i] = fixed[j] if j < len(fixed) else out[i]
        return out
    except Exception:
        return narr

def _resolve_user_lang_key(user_id: Optional[int], user_email: Optional[str]) -> str:
    """Resolve user's language key using user_id or, if absent, user_email.
    Returns one of: english, hindi, french, italian, spanish.
    """
    # Try by user_id first
    key = _get_user_language_key(user_id) if user_id is not None else "english"
    if key != "english":
        return key
    # If still english and we have an email, try resolving via email
    if user_email:
        try:
            db = Session()
            try:
                row = db.execute(text(
                    """
                    SELECT lm.lang_code AS lang_code
                    FROM public.users u
                    JOIN public.user_preferences up ON up.user_id = u.user_id
                    JOIN public.language_master lm ON lm.id = up.language_id
                    WHERE u.user_email = :email
                    LIMIT 1
                    """
                ), {"email": str(user_email)}).mappings().first()
                logger.info(f"[mlites] _resolve_user_lang_key via email: email={user_email} row={dict(row) if row else None}")
                if row and (row.get("lang_code") or "").strip():
                    return _language_key_from_code(str(row.get("lang_code")).strip())
            finally:
                try:
                    db.close()
                except Exception:
                    pass
        except Exception:
            pass
    return key


def _pick_tts_voice_for_key(lang_key: str) -> Dict[str, str]:
    """Pick a random TTS voice from VOICE_POOLS using a resolved language key."""
    key = (lang_key or "english").strip().lower()
    pool = VOICE_POOLS.get(key) or VOICE_POOLS["english"]
    try:
        return random.choice(pool)
    except Exception:
        return {"language_code": "en-US", "name": "en-US-Standard-B"}


def _maybe_translate_texts(texts: List[str], target_key: str) -> List[str]:
    """Generic helper to translate a list of strings to target language via Gemini.
    Returns original on failure or if target is English.
    """
    if not texts or target_key in (None, "", "english"):
        return texts
    try:
        lang_name = {
            "french": "French",
            "hindi": "Hindi",
            "italian": "Italian",
            "spanish": "Spanish",
        }.get(target_key)
        if not lang_name:
            return texts
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return texts
        genai.configure(api_key=api_key)
        model_name = os.getenv("GEMINI_PRIMARY_MODEL", "models/gemini-2.5-flash-lite")
        model = genai.GenerativeModel(model_name)
        import json as _json
        extra = ""
        if target_key == "hindi":
            extra = "Use Devanagari script (हिंदी लिपि), not transliteration."
        prompt = (
            "Translate the following JSON array of strings to " + lang_name + ".\n"
            "- Return ONLY a JSON array of strings with the SAME length and order.\n"
            "- Keep meaning natural; do not add explanations.\n" + extra + "\n"
        )
        text_in = _json.dumps(texts, ensure_ascii=False)
        resp = model.generate_content(prompt + "\n\nArray:\n" + text_in)
        out_text = resp.text or ""
        try:
            arr = _json.loads(out_text)
        except Exception:
            import re as _re
            m = _re.search(r"\[[\s\S]*\]", out_text)
            if not m:
                arr = None
            else:
                try:
                    arr = _json.loads(m.group(0))
                except Exception:
                    arr = None
        if isinstance(arr, list) and len(arr) == len(texts):
            return [str(x) for x in arr]
        # Fallback: per-item
        try:
            out_items: List[str] = []
            for s in texts:
                p = (
                    f"Translate the following to {lang_name}. Return ONLY the translated text, no quotes, no extra text. "
                    + ("Use Devanagari script (हिंदी लिपि)." if target_key == "hindi" else "")
                )
                r = model.generate_content(p + "\n\n" + str(s))
                txt = (r.text or "").strip()
                if len(txt) >= 2 and ((txt[0] == '"' and txt[-1] == '"') or (txt[0] == "'" and txt[-1] == "'")):
                    txt = txt[1:-1].strip()
                out_items.append(txt)
            if len(out_items) == len(texts):
                return out_items
        except Exception:
            pass
        return texts
    except Exception:
        return texts


def _find_font(candidates: List[str], size: int):
    """Return the first available font from candidates. If Pillow supports libraqm,
    enable complex script shaping via LAYOUT_RAQM for scripts like Devanagari.
    """
    for fp in candidates:
        try:
            if os.path.exists(fp):
                # Use complex text shaping if available (improves Devanagari rendering)
                try:
                    layout = getattr(ImageFont, "LAYOUT_RAQM", None)
                    if layout is not None:
                        return ImageFont.truetype(fp, size, layout_engine=layout)
                except Exception:
                    pass
                return ImageFont.truetype(fp, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None

def _assets_font_paths() -> Dict[str, str]:
    """Return possible bundled font file paths relative to repo for convenience."""
    base = Path(__file__).resolve().parent / "assets" / "fonts"
    return {
        "devanagari_bold": str((base / "NotoSansDevanagari-Bold.ttf").resolve()),
        "devanagari_regular": str((base / "NotoSansDevanagari-Regular.ttf").resolve()),
    }


def _create_title_image(text: str, out_path: Path, width: int = 1080, height: int = 1920, *, bg_path: Optional[Path] = None, bg_opacity: float = 0.2, language_key: str = "english", show_brand: bool = True, base_color: Optional[tuple] = None) -> None:
    # Base canvas with configurable tone (defaults to dark)
    _bc = base_color if base_color is not None else (26, 28, 34, 255)
    base = Image.new('RGBA', (width, height), color=_bc)
    if bg_path is not None:
        try:
            if isinstance(bg_path, (str, Path)) and Path(bg_path).exists():
                bg_img = Image.open(bg_path).convert('RGB')
                bg_fit = ImageOps.fit(bg_img, (width, height), method=Image.LANCZOS, centering=(0.5, 0.5))
                bg_rgba = bg_fit.convert('RGBA')
                alpha = max(0, min(255, int(255 * float(bg_opacity))))
                bg_rgba.putalpha(alpha)
                base = Image.alpha_composite(base, bg_rgba)
        except Exception:
            pass
    draw = ImageDraw.Draw(base)
    # Initialize defaults to avoid UnboundLocalError if any branch fails
    try:
        _def_font = ImageFont.load_default()
    except Exception:
        _def_font = None
    font_large = _def_font
    font_small = _def_font
    if language_key == "hindi":
        assets = _assets_font_paths()
        title_font = _find_font([
            assets.get("devanagari_bold", ""),
            "/usr/share/fonts/noto/NotoSansDevanagari-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
            r"C:\\Windows\\Fonts\\NirmalaB.ttf",
            r"C:\\Windows\\Fonts\\Nirmala.ttf",
            r"C:\\Windows\\Fonts\\Mangal.ttf",
            r"C:\\Windows\\Fonts\\Kokila.ttf",
            r"C:\\Windows\\Fonts\\arialuni.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ], 90)
        font_small = _find_font([
            assets.get("devanagari_regular", ""),
            "/usr/share/fonts/noto/NotoSansDevanagari-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
            r"C:\\Windows\\Fonts\\Nirmala.ttf",
            r"C:\\Windows\\Fonts\\Mangal.ttf",
            r"C:\\Windows\\Fonts\\Kokila.ttf",
            r"C:\\Windows\\Fonts\\arialuni.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ], 34)
    else:
        font_large = _find_font([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            r"C:\\Windows\\Fonts\\segoeuib.ttf",
            r"C:\\Windows\\Fonts\\arialbd.ttf",
        ], 90)
        font_small = _find_font([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            r"C:\\Windows\\Fonts\\segoeui.ttf",
            r"C:\\Windows\\Fonts\\arial.ttf",
        ], 34)
    # Final safety net if discovery returned None
    if font_large is None:
        try:
            font_large = ImageFont.load_default()
        except Exception:
            pass
    if font_small is None:
        try:
            font_small = ImageFont.load_default()
        except Exception:
            pass

    def text_w(s: str, f):
        try:
            bbox = draw.textbbox((0, 0), s, font=f)
            return bbox[2] - bbox[0]
        except Exception:
            try:
                return int(draw.textlength(s, font=f))  # type: ignore[attr-defined]
            except Exception:
                return len(s) * 16

    words = (text or "Mlites").strip()[:120].split()
    lines: List[str] = []
    current = ""
    max_w = width - 220
    for w in words:
        test = w if not current else current + " " + w
        if text_w(test, font_large) <= max_w:
            current = test
        else:
            if current:
                lines.append(current)
                current = w
            else:
                lines.append(w)
                current = ""
    if current:
        lines.append(current)

    total_h = 0
    line_sizes = []
    for ln in lines:
        try:
            bbox = draw.textbbox((0, 0), ln, font=font_large)
            w = bbox[2] - bbox[0]; h = bbox[3] - bbox[1]
        except Exception:
            w = text_w(ln, font_large); h = 84
        total_h += h + 12
        line_sizes.append((w, h))
    total_h -= 12 if lines else 0
    y = (height - total_h) // 2
    for i, ln in enumerate(lines):
        w, h = line_sizes[i]
        x = (width - w) // 2
        draw.text((x + 3, y + 3), ln, fill=(0, 0, 0), font=font_large)
        draw.text((x, y), ln, fill=(240, 240, 240), font=font_large)
        y += h + 12

    if show_brand:
        brand = "johnify mlites"
        try:
            bw = text_w(brand, font_small)
        except Exception:
            bw = len(brand) * 10
        bx = width - bw - 24
        by = height - 24 - 36
        draw.text((bx + 2, by + 2), brand, fill=(0, 0, 0), font=font_small)
        draw.text((bx, by), brand, fill=(200, 200, 200), font=font_small)

    try:
        out_img = base.convert('RGB')
    except Exception:
        # Fallback respects provided base_color when possible
        try:
            if isinstance(_bc, tuple) and len(_bc) >= 3:
                _rgb = (_bc[0], _bc[1], _bc[2])
            else:
                _rgb = (26, 28, 34)
        except Exception:
            _rgb = (26, 28, 34)
        out_img = Image.new('RGB', (width, height), color=_rgb)
    out_img.save(out_path)


def _canonicalize_content(structured_slides: List[Dict[str, Any]], narr: List[str], tags: List[str]) -> Dict[str, Any]:
    """Return a stable payload for storage and hashing. Excludes volatile fields like timestamps.
    Adds a content_hash field. Mirrors lites canonicalization shape.
    """
    slides_norm: List[Dict[str, Any]] = []
    for sl in structured_slides:
        if not isinstance(sl, dict):
            continue
        title = str(sl.get("title") or "").strip()
        bullets_in = sl.get("bullets") or []
        bullets = [str(b).strip() for b in bullets_in if isinstance(b, (str, int, float)) and str(b).strip()]
        slides_norm.append({"title": title, "bullets": bullets})
    narr_norm = [str(x).strip() for x in narr if isinstance(x, (str, int, float))]
    tags_norm = [str(x).strip().lower() for x in tags if isinstance(x, (str, int, float))]
    base = {"slides": slides_norm, "narrations": narr_norm, "tags": tags_norm}
    try:
        canon = json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        import hashlib
        h = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    except Exception:
        h = ""
    base["content_hash"] = h
    return base


def _narrations_to_mp3(narrations: List[str], out_dir: str, voice_choice: Optional[Dict[str, str]] = None) -> Path:
    from google.cloud import texttospeech
    out_p = Path(out_dir)
    if out_p.exists():
        import shutil
        shutil.rmtree(out_p)
    out_p.mkdir(parents=True, exist_ok=True)
    client = texttospeech.TextToSpeechClient()
    # Choose voice
    vc_lang = (voice_choice or {}).get("language_code") or "en-US"
    vc_name = (voice_choice or {}).get("name") or "en-US-Standard-B"
    voice = texttospeech.VoiceSelectionParams(
        language_code=vc_lang,
        name=vc_name,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.05,
        pitch=0.0,
        sample_rate_hertz=44100,
    )
    attempts = int(os.getenv("TTS_MAX_RETRIES", "5") or "5")
    for i, narration in enumerate(narrations):
        synthesis_input = texttospeech.SynthesisInput(text=narration)
        last_err: Optional[Exception] = None
        for attempt in range(1, max(1, attempts) + 1):
            _TTS_SEM.acquire()
            try:
                response = client.synthesize_speech(
                    input=synthesis_input, voice=voice, audio_config=audio_config
                )
                mp3_path = out_p / f"s{i+1:03d}.mp3"
                mp3_path.write_bytes(response.audio_content)
                logger.info(f"Created {mp3_path}")
                last_err = None
                break
            except Exception as e:
                last_err = e
                logger.warning(f"[mlites] TTS synth attempt {attempt} failed (voice={vc_lang}/{vc_name}): {e}")
                if attempt >= attempts:
                    _TTS_SEM.release()
                    raise
                _TTS_SEM.release()
                _sleep_backoff(attempt, base=0.6, factor=2.0, cap=10.0, jitter=0.35)
                continue
            finally:
                try:
                    if last_err is None:
                        _TTS_SEM.release()
                except Exception:
                    pass
        time.sleep(random.uniform(0.05, 0.2))
    return out_p


def _get_audio_duration(mp3: Path) -> float:
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', str(mp3)],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(result.stdout or '{}')
        return float(data.get('format', {}).get('duration', 0.0))
    except subprocess.TimeoutExpired:
        logger.warning(f"duration error: ffprobe timeout for {mp3}")
        return 0.0
    except Exception as e:
        logger.warning(f"duration error: {e}")
        return 0.0


def _create_slide_video(img: Path, mp3: Path, out_mp4: Path, duration_override: Optional[float] = None):
    try:
        duration = max(0.1, float(duration_override) if duration_override is not None else float(_get_audio_duration(mp3)))
        subprocess.run([
            'ffmpeg','-y','-loop','1','-i',str(img),'-i',str(mp3),'-t',str(duration),
            '-c:v','libx264','-preset','ultrafast','-tune','stillimage','-crf','28','-r','30','-threads','1','-pix_fmt','yuv420p',
            '-vf','fps=30,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1',
            '-c:a','aac','-ar','44100','-ac','2','-b:a','128k','-shortest', str(out_mp4)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
        return out_mp4
    except subprocess.TimeoutExpired:
        logger.error(f"segment error: ffmpeg timeout creating segment {out_mp4}")
        raise
    except Exception as e:
        logger.error(f"segment error: {e}")
        raise


def _stitch_images_and_audio_to_video(img_dir: Path, aud_dir: Path, out_mp4: Path):
    import tempfile, shutil, re
    temp_dir = Path(tempfile.mkdtemp())
    try:
        imgs = sorted(Path(img_dir).glob('slide_*.png'))
        imgs = [p for p in imgs if re.match(r'^slide_\d{3}\.png$', p.name)]
        mp3s = sorted(Path(aud_dir).glob('*.mp3'))
        if not imgs:
            raise ValueError('No slide images found')
        if not mp3s:
            silent = temp_dir / 'silent.mp3'
            subprocess.run(['ffmpeg','-y','-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100','-t','5','-c:a','libmp3lame',str(silent)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            mp3s = [silent] * len(imgs)
        pair_n = min(len(imgs), len(mp3s))
        # Educational deep-dive target: ~90s total
        max_total = 92.0  # soft cap ~92s
        min_total = 85.0  # ensure at least 85s
        min_per = 2.2
        segs = []
        total_used = 0.0

        # Treat the final slide as the brand endcard; fix its duration to 2s
        brand_dur = 2.0 if pair_n >= 1 else 0.0
        content_count = max(0, pair_n - 1)
        # Distribute remaining budget across content slides
        remaining_budget = max(0.0, max_total - brand_dur)
        per_cap_content = max(min_per, remaining_budget / float(max(1, content_count))) if content_count > 0 else 0.0
        per_cap_content = min(per_cap_content, 14.0)

        for i in range(pair_n):
            seg = temp_dir / f"seg_{i+1:03d}.mp4"
            if i == pair_n - 1:
                # brand/endcard
                use_dur = brand_dur
            else:
                orig = _get_audio_duration(mp3s[i])
                use_dur = min(per_cap_content, max(min_per, orig))
            _create_slide_video(imgs[i], mp3s[i], seg, duration_override=use_dur)
            segs.append(seg)
            total_used += float(use_dur)
        # If total duration is below 60s, append a final silent segment using last CONTENT image (not brand)
        if total_used < min_total:
            try:
                need = float(min_total - total_used)
                need = max(0.5, min(need, 15.0))
                # Choose last content image if available; else fall back to last image
                last_img_idx = pair_n - 2 if pair_n >= 2 else max(0, pair_n - 1)
                last_img = imgs[last_img_idx]
                silent_mp3 = temp_dir / 'pad_silent.mp3'
                subprocess.run(['ffmpeg','-y','-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100','-t',str(round(need,2)),'-c:a','libmp3lame',str(silent_mp3)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                seg_pad = temp_dir / f"seg_{pair_n+1:03d}.mp4"
                _create_slide_video(last_img, silent_mp3, seg_pad, duration_override=need)
                segs.append(seg_pad)
            except Exception as e:
                logger.warning(f"padding segment failed: {e}")
        if not segs:
            raise ValueError('No segments created')
        concat = temp_dir / 'concat.txt'
        with concat.open('w', encoding='utf-8') as f:
            for s in segs:
                f.write(f"file '{s.resolve()}'\n")
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            'ffmpeg','-y','-f','concat','-safe','0','-i',str(concat),
            '-c:v','libx264','-preset','ultrafast','-crf','28','-r','30','-threads','1','-pix_fmt','yuv420p',
            '-c:a','aac','-ar','44100','-ac','2','-b:a','128k','-movflags','+faststart', str(out_mp4)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        logger.info(f"Final video: {out_mp4}")
        return out_mp4
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


def _get_or_create_mlite_sub_topic_id(db, topic_id: int, sub_topic: str) -> Optional[int]:
    """Insert sub-topic if not exists and return its id. Returns None on failure."""
    try:
        if not sub_topic:
            return None
        # Try select existing
        row = db.execute(text(
            """
            SELECT id FROM public.lites_sub_topics
            WHERE topic_id = :tid AND sub_topic = :st
            LIMIT 1
            """
        ), {"tid": int(topic_id), "st": sub_topic}).mappings().first()
        if row and "id" in row:
            return int(row["id"])  # type: ignore[index]
        # Insert new
        row2 = db.execute(text(
            """
            INSERT INTO public.lites_sub_topics (topic_id, sub_topic, created_on)
            VALUES (:tid, :st, NOW())
            RETURNING id
            """
        ), {"tid": int(topic_id), "st": sub_topic}).mappings().first()
        db.commit()
        return int(row2["id"]) if row2 and "id" in row2 else None  # type: ignore[index]
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _draw_text_slide(
    title: str,
    content: str,
    out_path: Path,
    width: int = 1080,
    height: int = 1920,
    mode: str = "full",
    text_color=(0, 0, 0),
    bg_path: Optional[Path] = None,
    bg_opacity: float = 0.2,
    language_key: str = "english",
):
    # Base canvas
    base = Image.new('RGBA', (width, height), color=(245, 246, 250, 255))
    # Optional background image (e.g., thumbnail/title) at target opacity; skip for brand slides
    if mode != "brand" and bg_path is not None:
        try:
            if isinstance(bg_path, (str, Path)) and Path(bg_path).exists():
                bg_img = Image.open(bg_path).convert('RGB')
                # Cover fit while preserving aspect ratio
                bg_fit = ImageOps.fit(bg_img, (width, height), method=Image.LANCZOS, centering=(0.5, 0.5))
                bg_rgba = bg_fit.convert('RGBA')
                alpha = max(0, min(255, int(255 * float(bg_opacity))))
                bg_rgba.putalpha(alpha)
                base = Image.alpha_composite(base, bg_rgba)
        except Exception:
            pass
    draw = ImageDraw.Draw(base)
    # Initialize defaults
    try:
        _def_font = ImageFont.load_default()
    except Exception:
        _def_font = None
    title_font = _def_font
    body_font = _def_font
    # Choose fonts depending on language/script (best-effort cross-platform fallbacks)
    if language_key == "hindi":
        assets = _assets_font_paths()
        title_font = _find_font([
            assets.get("devanagari_bold", ""),
            "/usr/share/fonts/noto/NotoSansDevanagari-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
            r"C:\\Windows\\Fonts\\NirmalaB.ttf",
            r"C:\\Windows\\Fonts\\Nirmala.ttf",
            r"C:\\Windows\\Fonts\\Mangal.ttf",
            r"C:\\Windows\\Fonts\\Kokila.ttf",
            r"C:\\Windows\\Fonts\\arialuni.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ], 72)
        body_font = _find_font([
            assets.get("devanagari_regular", ""),
            "/usr/share/fonts/noto/NotoSansDevanagari-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
            r"C:\\Windows\\Fonts\\Nirmala.ttf",
            r"C:\\Windows\\Fonts\\Mangal.ttf",
            r"C:\\Windows\\Fonts\\Kokila.ttf",
            r"C:\\Windows\\Fonts\\arialuni.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ], 36)
    else:
        title_font = _find_font([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            r"C:\\Windows\\Fonts\\segoeuib.ttf",
            r"C:\\Windows\\Fonts\\arialbd.ttf",
        ], 72)
        body_font = _find_font([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            r"C:\\Windows\\Fonts\\segoeui.ttf",
            r"C:\\Windows\\Fonts\\arial.ttf",
        ], 36)
    # Final safety net
    if title_font is None:
        try:
            title_font = ImageFont.load_default()
        except Exception:
            pass
    if body_font is None:
        try:
            body_font = ImageFont.load_default()
        except Exception:
            pass

    if mode == "brand":
        try:
            tb = draw.textbbox((0, 0), title, font=title_font)
            tw, th = tb[2]-tb[0], tb[3]-tb[1]
        except Exception:
            tw = len(title) * 16; th = 64
        tx = (width - tw) // 2
        ty = (height - th) // 2
        draw.text((tx+2, ty+2), title, fill=(0,0,0), font=title_font)
        draw.text((tx, ty), title, fill=(20,20,20), font=title_font)
        try:
            out_img = base.convert('RGB')
        except Exception:
            out_img = Image.new('RGB', (width, height), color=(245, 246, 250))
        out_img.save(out_path)
        return

    pad_x = 48
    pad_y = 56
    try:
        tb = draw.textbbox((0, 0), title, font=title_font)
        tw, th = tb[2]-tb[0], tb[3]-tb[1]
    except Exception:
        tw = len(title) * 16; th = 64
    tx = pad_x
    ty = pad_y
    draw.text((tx+2, ty+2), title, fill=(0,0,0), font=title_font)
    draw.text((tx, ty), title, fill=(20,20,20), font=title_font)

    y = ty + th + 24
    max_w = width - 2*pad_x
    max_lines = 3  # reels-like: very few lines
    lines_rendered = 0
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            y += 8
            continue
        # Do NOT force bullet markers for a reels aesthetic
        words = line.split()
        cur = ""
        while words:
            w = words.pop(0)
            test = w if not cur else cur + " " + w
            try:
                tb = draw.textbbox((0, 0), test, font=body_font)
                tw = tb[2]-tb[0]
            except Exception:
                tw = len(test) * 12
            if tw <= max_w:
                cur = test
            else:
                if cur:
                    draw.text((pad_x, y), cur, fill=text_color, font=body_font)
                    y += 42
                    cur = w
                    lines_rendered += 1
                    if lines_rendered >= max_lines:
                        words = []
                        break
                else:
                    draw.text((pad_x, y), w, fill=text_color, font=body_font)
                    y += 42
        if cur and lines_rendered < max_lines:
            draw.text((pad_x, y), cur, fill=text_color, font=body_font)
            y += 46
            lines_rendered += 1
        if lines_rendered >= max_lines:
            break
    base.save(out_path)


# ---- Gemini content generation (mobile-optimized) ----

def _gemini_generate_mobile(topic: str, avoid_subtopics: Optional[List[str]] = None, context_summaries: Optional[List[str]] = None, focus_subtopic: Optional[str] = None) -> Dict[str, Any]:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set for Gemini")
    genai.configure(api_key=api_key)
    model_name = _GEM_PRIMARY_MODEL
    avoid_subtopics = [s.strip() for s in (avoid_subtopics or []) if s and str(s).strip()]
    ctx_lines = []
    if avoid_subtopics:
        ctx_lines.append("Avoid these sub-topics entirely (choose a DIFFERENT, specific angle): " + "; ".join(sorted(set(avoid_subtopics))[:30]))
    if context_summaries:
        # Give very light context of previous coverage to encourage novelty.
        short = [x.strip() for x in context_summaries if x and str(x).strip()]
        if short:
            ctx_lines.append("Previously covered ideas (do NOT repeat): " + "; ".join(short[:10]))

    prompt = (
        "You create EDUCATIONAL, vertical reels with a NATURAL, STORY-LIKE FLOW. Return ONLY strict JSON with keys: slides, narrations, tags.\n"
        "- Goal: an 85-95 second deep-dive that explains ONE SPECIFIC SUB-TOPIC thoroughly (depth over breadth).\n"
        "- slides: array of 6-9 objects: {title: string, bullets: array of 1-2 VERY SHORT on-screen phrases (3-6 words, no punctuation)}.\n"
        "  Keep on-screen text ultra-minimal (quick reading). No numbered or dash bullets. Emojis ok sparingly.\n"
        "- narrations: array of same length; narration must be CONTINUOUS across slides and TEACH the sub-topic clearly.\n"
        "  Use simple explanations, tiny examples/imagery, and smooth transitions (no listicles).\n"
        "- tags: array of 5-10 lowercase single-word keywords.\n"
        f"Topic: {topic}\n"
        + (f"Focus sub-topic (strictly stay on this): {focus_subtopic}\n" if (focus_subtopic and str(focus_subtopic).strip()) else "")
        + ("\n" + "\n".join(ctx_lines) if ctx_lines else "")
        + "\nConstraints:\n- Focus on DEPTH of a single sub-topic, not breadth.\n- Keep the story coherent across slides; flowing, conversational tone.\n- Use concrete examples or imagery to maintain pace.\n- Optimize for watch time: short sentences, minimal filler.\n- Ensure the sub-topic/angle and content are NEW relative to the provided avoid list and previous coverage."
    )
    # Retry Gemini with concurrency limiting and per-model RPM
    attempts = int(os.getenv("GEMINI_MAX_RETRIES", "5") or "5")
    text = ""
    last_err: Optional[Exception] = None
    for attempt in range(1, max(1, attempts) + 1):
        _gemini_acquire_slot_for(model_name)
        _GEM_SEM.acquire()
        try:
            model = genai.GenerativeModel(model_name)
            resp = model.generate_content(prompt)
            try:
                text = resp.text or ""
            except Exception:
                text = str(resp)
            last_err = None
            break
        except Exception as e:
            last_err = e
            logger.warning(f"[mlites] Gemini generate attempt {attempt} failed: {e}")
            emsg = str(e)
            if ("429" in emsg or "Rate" in emsg or "rate" in emsg):
                if model_name == _GEM_PRIMARY_MODEL:
                    logger.info(f"[mlites] Switching Gemini model to fallback1 {_GEM_FALLBACK_MODEL} due to rate limit")
                    model_name = _GEM_FALLBACK_MODEL
                    _GEM_SEM.release()
                    _sleep_backoff(attempt, base=0.4, factor=1.8, cap=8.0, jitter=0.3)
                    continue
                elif model_name == _GEM_FALLBACK_MODEL:
                    logger.info(f"[mlites] Switching Gemini model to fallback2 {_GEM_FALLBACK2_MODEL} due to rate limit")
                    model_name = _GEM_FALLBACK2_MODEL
                    _GEM_SEM.release()
                    _sleep_backoff(attempt, base=0.4, factor=1.8, cap=8.0, jitter=0.3)
                    continue
            if attempt >= attempts:
                _GEM_SEM.release()
                raise
            _GEM_SEM.release()
            _sleep_backoff(attempt, base=0.6, factor=2.0, cap=10.0, jitter=0.35)
            continue
        finally:
            try:
                if last_err is None:
                    _GEM_SEM.release()
            except Exception:
                pass

    data: Dict[str, Any] = {"slides": [], "narrations": [], "tags": []}
    try:
        data = json.loads(text)
    except Exception:
        import re
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                pass

    slides = data.get("slides") or []
    narr = data.get("narrations") or []
    tags = data.get("tags") or []
    if not isinstance(slides, list) or len(slides) == 0:
        slides = [
            {"title": topic.strip().title() or "Overview", "bullets": ["What/Why", "Use-cases"]},
            {"title": "Core", "bullets": ["Key idea", "Tip"]},
            {"title": "Example", "bullets": ["Case", "Result"]},
            {"title": "Wrap", "bullets": ["Takeaway", "Next"]},
        ]
    if not isinstance(narr, list) or len(narr) < len(slides):
        narr = [f"Here’s a fast, flowing look at {topic}—short, punchy, and cohesive. Keep watching."] * len(slides)
    narr = narr[:len(slides)]
    if not isinstance(tags, list) or len(tags) == 0:
        tags = [topic.split(" ")[0].lower(), "basics", "mobile"]
    return {"slides": slides, "narrations": narr, "tags": tags}


def _fetch_previous_topic_context(db, user_id: int, topic: str) -> Tuple[Set[str], Set[str], List[str]]:
    """Return (prior_subtopics, prior_hashes, prior_summaries) for this user's topic across mlites.
    - prior_subtopics parsed from post_topic after ' - ' when present.
    - prior_hashes from content JSON's content_hash.
    - prior_summaries as a short list of key slide titles to bias novelty.
    """
    subtopics: Set[str] = set()
    hashes: Set[str] = set()
    summaries: List[str] = []
    try:
        rows = db.execute(text(
            """
            SELECT post_topic, content
            FROM public.user_posts
            WHERE user_id = :uid AND type = 'mlites' AND (
              post_topic = :topic OR post_topic ILIKE :prefix
            )
            ORDER BY created_on DESC
            """
        ), {"uid": int(user_id), "topic": topic, "prefix": f"{topic} - %"}).mappings().all()
        for r in rows:
            try:
                pt = str(r.get("post_topic") or "")
                if " - " in pt:
                    sub = pt.split(" - ", 1)[1].strip()
                    if sub:
                        subtopics.add(sub)
            except Exception:
                pass
            try:
                cont = r.get("content")
                if isinstance(cont, str):
                    cont_json = json.loads(cont)
                else:
                    cont_json = cont or {}
                h = str((cont_json or {}).get("content_hash") or "").strip()
                if h:
                    hashes.add(h)
                # build a tiny summary from first slide titles
                sl = cont_json.get("slides") or []
                if isinstance(sl, list) and sl:
                    title0 = str((sl[0] or {}).get("title") or "").strip()
                    if title0:
                        summaries.append(title0)
            except Exception:
                continue
    except Exception:
        pass
    return subtopics, hashes, summaries[:12]


def _pick_focus_subtopic(db, user_id: int, topic: str, avoid: Optional[Set[str]] = None) -> Optional[str]:
    """Pick a focus subtopic for the given user's topic from lites_sub_topics.
    Prefer one not present in 'avoid'. Returns None if none available.
    """
    try:
        rows = db.execute(text(
            """
            SELECT st.sub_topic
            FROM public.lites_sub_topics st
            JOIN public.lites_topics lt ON lt.id = st.topic_id
            WHERE lt.user_id = :uid AND lt.topic = :topic
            ORDER BY st.created_on ASC
            LIMIT 100
            """
        ), {"uid": int(user_id), "topic": topic}).mappings().all()
        subs = [r["sub_topic"] for r in rows if r and "sub_topic" in r]
        if not subs:
            return None
        avoid = avoid or set()
        for s in subs:
            if s and s not in avoid:
                return s
        return subs[0]
    except Exception:
        return None


# ---- Request models ----
class MLiteTopic(BaseModel):
    topic: str
    minutes_per_day: int = 2


class CreateMLitesRequest(BaseModel):
    topics: List[MLiteTopic]
    user_email: Optional[str] = None
    user_id: Optional[int] = None


@router.post("")
async def create_mlites(req: CreateMLitesRequest, bg: BackgroundTasks, current_user: AuthUser = Depends(get_current_user)):
    if not req or not isinstance(req.topics, list) or len(req.topics) == 0:
        raise HTTPException(status_code=400, detail="At least one topic is required")

    allowed = {1, 2, 3, 4, 5, 10, 15}
    topics: List[Dict[str, Any]] = []
    for t in req.topics[:50]:
        tp = (t.topic or "").strip()
        if not tp:
            continue
        mpd = int(t.minutes_per_day or 2)
        if mpd not in allowed:
            mpd = 2
        topics.append({"topic": tp, "minutes_per_day": mpd})

    if not topics:
        raise HTTPException(status_code=400, detail="All topics are empty")

    def _run(items: List[Dict[str, Any]], user_email: Optional[str], user_id: Optional[int], ts: int):
        try:
            logger.info(f"[mlites] _run start for user_id={user_id} email={user_email}")
            base_dir = _get_generated_root()
            base_dir.mkdir(parents=True, exist_ok=True)
            for item in items:
                tp = item["topic"]
                # Ensure topic subscription row exists for this user
                try:
                    if user_id is not None:
                        dbp = Session()
                        try:
                            _ensure_mlites_tables(dbp)
                            dbp.execute(text(
                                """
                                INSERT INTO public.lites_topics (user_id, topic, minutes_per_day, active)
                                VALUES (:uid, :topic, :mpd, TRUE)
                                ON CONFLICT (user_id, topic)
                                DO UPDATE SET minutes_per_day = EXCLUDED.minutes_per_day, active = TRUE, updated_on = NOW()
                                """
                            ), {"uid": int(user_id), "topic": tp, "mpd": int(item.get("minutes_per_day", 2))})
                            dbp.commit()
                        finally:
                            dbp.close()
                except Exception as e:
                    logger.warning(f"[mlites] topic upsert failed: {e}")

                # Choose a single focus subtopic for deep-dive if available
                focus_sub = None
                try:
                    if user_id is not None:
                        dbp_pick = Session()
                        try:
                            focus_sub = _pick_focus_subtopic(dbp_pick, int(user_id), tp, avoid=prior_subtopics)
                        finally:
                            dbp_pick.close()
                except Exception:
                    focus_sub = None

                combined = f"{tp} - {focus_sub}" if (focus_sub and str(focus_sub).strip()) else tp
                safe = _sanitize_filename(combined)
                out_dir = base_dir / f"mlites_{safe}_{ts}"
                dirs = _ensure_dirs(out_dir)

                # 1) Fetch prior context for uniqueness
                prior_subtopics: Set[str] = set()
                prior_hashes: Set[str] = set()
                prior_summaries: List[str] = []
                try:
                    if user_id is not None:
                        dbp_ctx = Session()
                        try:
                            prior_subtopics, prior_hashes, prior_summaries = _fetch_previous_topic_context(dbp_ctx, int(user_id), tp)
                        finally:
                            dbp_ctx.close()
                except Exception:
                    pass

                # 2) Slides + Narrations + tags via Gemini (mobile) with avoidance
                logger.info(f"[mlites] Generating mobile content for: {combined} (avoid {len(prior_subtopics)} subtopics, {len(prior_hashes)} hashes)")

                # Regenerate up to 3 times if collision by subtopic or content_hash
                max_attempts = 3
                attempt = 0
                while True:
                    attempt += 1
                    gem = _gemini_generate_mobile(tp, avoid_subtopics=list(prior_subtopics), context_summaries=prior_summaries, focus_subtopic=focus_sub)
                    structured = gem.get("slides", [])
                    narr = gem.get("narrations") or []
                    # Translate narrations if user's preferred language is not English
                    try:
                        lang_key = _resolve_user_lang_key(user_id, user_email)
                        logger.info(f"[mlites] user language key: {lang_key}")
                        narr = _maybe_translate_narrations(narr, lang_key)
                        narr = _enforce_translation(narr, lang_key)
                    except Exception:
                        pass
                    tags = gem.get("tags") or []
                    # Derive subtopic similar to previous logic
                    derived_sub_topic = (focus_sub[:255] if (focus_sub and isinstance(focus_sub, str)) else None)
                    try:
                        if not derived_sub_topic and isinstance(structured, list) and structured:
                            t0 = (structured[0].get("title") or "").strip()
                            if t0 and t0.lower() != "johnify":
                                derived_sub_topic = t0[:255]
                    except Exception:
                        derived_sub_topic = None
                    try:
                        if derived_sub_topic and derived_sub_topic.strip().lower() == tp.strip().lower():
                            derived_sub_topic = None
                    except Exception:
                        pass
                    # Compute canonical content hash for collision detection
                    tmp_content = _canonicalize_content(structured, narr[:len(structured)] if isinstance(narr, list) else [], tags)
                    ch = tmp_content.get("content_hash") or ""
                    # If a focus subtopic is chosen, allow it even if seen before
                    sub_conflict = (not focus_sub) and (derived_sub_topic and derived_sub_topic in prior_subtopics)
                    hash_conflict = ch and ch in prior_hashes
                    if not sub_conflict and not hash_conflict:
                        break
                    logger.info(f"[mlites] collision detected (attempt {attempt}) sub_conflict={bool(sub_conflict)} hash_conflict={bool(hash_conflict)}; regenerating...")
                    if attempt >= max_attempts:
                        # Give up and proceed with latest gem
                        break

                # Build markdown slides
                # Use the last generated gem from the loop
                structured = gem.get("slides", [])
                # derived_sub_topic already computed above in the loop
                slides: List[str] = []
                for sl in structured:
                    title = (sl.get("title") or "Slide").strip()
                    bullets = sl.get("bullets") or []
                    bullets = [b for b in bullets if isinstance(b, str) and b.strip()]
                    body = "\n".join([f"- {b.strip()}" if not b.strip().startswith('-') else b.strip() for b in bullets])
                    slides.append(f"## {title}\n{body}".strip())
                narr = gem.get("narrations") or []
                if not isinstance(narr, list):
                    narr = []
                if len(narr) < len(slides):
                    narr.extend([f"Quick take on {combined}. Focus on the essentials."] * (len(slides) - len(narr)))
                narr = narr[:len(slides)]
                tags = gem.get("tags") or []
                try:
                    (out_dir / "tags.json").write_text(json.dumps(tags, ensure_ascii=False, indent=2), encoding='utf-8')
                except Exception:
                    pass

                # End card
                slides.append("## Johnify\n")
                narr.append("Thanks for watching")

                # Save slides.md
                md_file = out_dir / "slides.md"
                try:
                    with md_file.open('w', encoding='utf-8') as f:
                        f.write("---\nmarp: true\ntheme: default\npaginate: true\n---\n\n")
                        for i, (s, n) in enumerate(zip(slides, narr)):
                            if i > 0:
                                f.write("\n---\n\n")
                            s = (s or "").strip()
                            if s and not any(line.strip().startswith('#') for line in s.split('\n')[:3]):
                                s = f"## Slide {i+1}\n" + s
                            has_bullets = any(line.strip().startswith('-') for line in s.split('\n'))
                            is_brand_endcard = any((ln.strip().lower().startswith('## johnify')) for ln in s.split('\n')[:3])
                            if not has_bullets and not is_brand_endcard:
                                s += "\n- Point 1\n- Point 2"
                            s = '\n'.join([ln for ln in s.split('\n') if ln.strip()])
                            f.write(f"{s}\n\n<!-- NARRATION: {n} -->\n")
                except Exception as e:
                    logger.error(f"[mlites] failed to write slides.md: {e}")

                # 4) Render images (portrait)
                images_dir = dirs["images"]
                try:
                    # Pre-generate a shared background/thumbnail (respects MLITES_THUMBNAIL_AI/global switch)
                    thumb = out_dir / "thumbnail.jpg"
                    try:
                        from .main import generate_thumbnail_with_fallbacks  # type: ignore
                        if (not thumb.exists()) or (thumb.exists() and thumb.stat().st_size < 1024):
                            _ok = generate_thumbnail_with_fallbacks(tp, str(thumb), label="mlites", width=720, height=1280)
                            if not _ok:
                                # As absolute last fallback, create a plain PIL slide for background
                                _draw_text_slide(combined, "", images_dir / "_bg_tmp.png", width=1080, height=1920, mode="brand")
                                Image.open(images_dir / "_bg_tmp.png").convert('RGB').save(thumb, format='JPEG', quality=86)
                    except Exception:
                        pass
                    # Localize the big title according to user language
                    try:
                        lang_key = _resolve_user_lang_key(user_id, user_email)
                        if lang_key and lang_key != "english":
                            tr = _maybe_translate_texts([combined], lang_key)
                            if isinstance(tr, list) and tr:
                                combined_local = tr[0]
                            else:
                                combined_local = combined
                        else:
                            combined_local = combined
                    except Exception:
                        combined_local = combined
                    title_png = images_dir / "slide_000.png"
                    _create_title_image(combined_local, title_png, 1080, 1920, bg_path=thumb, bg_opacity=_MLITES_BG_OPACITY, language_key=lang_key if 'lang_key' in locals() else 'english')
                    raw = md_file.read_text(encoding='utf-8') if md_file.exists() else ""
                    raw = raw.split('---', 2)
                    content_only = raw[2] if len(raw) >= 3 else raw[0]
                    blocks = [b.strip() for b in content_only.split('---') if b.strip()]
                    import re as _re
                    rendered = []
                    for b in blocks:
                        b2 = _re.sub(r'<!--.*?-->', '', b, flags=_re.DOTALL).strip()
                        title_line = ""
                        for ln in b2.split('\n')[:3]:
                            if ln.strip().startswith('## '):
                                title_line = ln.strip()[3:].strip()
                                break
                        if not title_line:
                            title_line = "Slide"
                        body = '\n'.join([ln for ln in b2.split('\n') if not ln.strip().startswith('## ')])
                        rendered.append((title_line, body))
                    # Localize per-slide title and body
                    try:
                        lang_key2 = lang_key if 'lang_key' in locals() else _get_user_language_key(user_id)
                        if lang_key2 and lang_key2 != "english":
                            titles = [ti for (ti, _b) in rendered]
                            bodies = [body for (_ti, body) in rendered]
                            titles_tr = _maybe_translate_texts(titles, lang_key2)
                            bodies_tr = _maybe_translate_texts(bodies, lang_key2)
                            rendered_local = list(zip(titles_tr or titles, bodies_tr or bodies))
                        else:
                            rendered_local = rendered
                    except Exception:
                        rendered_local = rendered

                    for idx, (ti, body) in enumerate(rendered_local, 1):
                        outp = images_dir / f"slide_{idx:03d}.png"
                        is_brand_endcard = (ti.strip().lower() == "johnify") and (not (body or "").strip())
                        if is_brand_endcard:
                            _draw_text_slide(ti, body, outp, width=1080, height=1920, mode="brand", language_key=lang_key2 if 'lang_key2' in locals() else 'english')
                        else:
                            _draw_text_slide(ti, body, outp, width=1080, height=1920, bg_path=thumb, bg_opacity=_MLITES_BG_OPACITY, language_key=lang_key2 if 'lang_key2' in locals() else 'english')
                except Exception as e:
                    logger.error(f"[mlites] image render error: {e}")

                # 5) TTS
                audio_dir = dirs["audio"]
                audio_files: List[str] = []
                image_files: List[str] = []
                try:
                    # Pick voice using the SAME language key used for translation/text
                    voice_choice = _pick_tts_voice_for_key(lang_key if 'lang_key' in locals() else _resolve_user_lang_key(user_id, user_email))
                    try:
                        logger.info(f"[mlites] TTS voice selected: lang={voice_choice.get('language_code')} name={voice_choice.get('name')}")
                    except Exception:
                        pass
                    tts_dir = _narrations_to_mp3(narr, str(audio_dir), voice_choice=voice_choice)
                    audio_files = sorted([str(p) for p in Path(tts_dir).glob('*.mp3')])
                    title_png = images_dir / "slide_000.png"
                    if title_png.exists():
                        silent_mp3 = Path(tts_dir) / "s000.mp3"
                        if not silent_mp3.exists() or os.path.getsize(silent_mp3) == 0:
                            subprocess.run(['ffmpeg','-y','-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100','-t','1.25','-c:a','libmp3lame',str(silent_mp3)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                        audio_files = sorted([str(p) for p in Path(tts_dir).glob('*.mp3')])
                except Exception as e:
                    logger.error(f"[mlites] audio generation error: {e}")

                # 6) Pair
                try:
                    image_files = sorted([str(p) for p in images_dir.glob('*.png')])
                    min_len = min(len(image_files), len(audio_files))
                    if min_len == 0:
                        raise ValueError("no images/audio")
                    image_files = image_files[:min_len]
                    audio_files = audio_files[:min_len]
                except Exception as e:
                    logger.error(f"[mlites] pairing error: {e}")

                # 7) Stitch video (portrait)
                video_path = out_dir / f"mlites_{safe}_{ts}.mp4"
                try:
                    _stitch_images_and_audio_to_video(
                        img_dir=Path(image_files[0]).parent,
                        aud_dir=Path(audio_files[0]).parent,
                        out_mp4=video_path
                    )
                except Exception as e:
                    logger.error(f"[mlites] video stitch error: {e}")

                # 8) Thumbnail: already generated above; do not overwrite if valid
                try:
                    thumb = out_dir / "thumbnail.jpg"
                    if not thumb.exists() or thumb.stat().st_size < 1024:
                        # As a safety net, derive from title image
                        if (images_dir / "slide_000.png").exists():
                            Image.open(images_dir / "slide_000.png").convert('RGB').save(thumb, format='JPEG', quality=88)
                        elif image_files:
                            Image.open(image_files[0]).convert('RGB').save(thumb, format='JPEG', quality=88)
                except Exception as e:
                    logger.error(f"[mlites] thumbnail error: {e}")

                # 9) Publish SSE + Persist DB
                try:
                    if user_id is not None:
                        GENERATED_ROOT = _get_generated_root()
                        ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
                        IS_PRODUCTION = ENVIRONMENT == "production"
                        base_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip('/')

                        # Try GCS uploads (production) for video and thumbnail
                        video_https_url = ""
                        thumb_https_url = ""
                        try:
                            folder = f"lites_{safe}_{ts}"
                            obj_name = f"lites_{safe}_{ts}.mp4"
                            up = maybe_upload_and_url(
                                video_path,
                                parts=["content", "lites", folder, obj_name],
                                content_type="video/mp4",
                                make_public=True,
                            )
                            video_https_url = up.get("https_url", "")
                        except Exception as e:
                            logger.warning(f"[mlites] video upload skipped/failed: {e}")
                        try:
                            thumb_path = out_dir / "thumbnail.jpg"
                            if thumb_path.exists():
                                thumb_obj_name = f"lites_{safe}_{ts}_thumbnail.jpg"
                                up_t = maybe_upload_and_url(
                                    thumb_path,
                                    parts=["content", "lites", folder, thumb_obj_name],
                                    content_type="image/jpeg",
                                    make_public=True,
                                )
                                thumb_https_url = up_t.get("https_url", "")
                                # Also upload a canonical copy named exactly 'thumbnail.jpg' for frontend URL derivation
                                try:
                                    up_t2 = maybe_upload_and_url(
                                        thumb_path,
                                        parts=["content", "lites", folder, "thumbnail.jpg"],
                                        content_type="image/jpeg",
                                        make_public=True,
                                    )
                                    # Prefer canonical URL if available
                                    thumb_https_url = up_t2.get("https_url", thumb_https_url)
                                except Exception as e2:
                                    logger.warning(f"[mlites] secondary thumbnail.jpg upload skipped/failed: {e2}")
                        except Exception as e:
                            logger.warning(f"[mlites] thumbnail upload skipped/failed: {e}")

                        # Local fallback URLs
                        try:
                            rel_video = video_path.resolve().relative_to(GENERATED_ROOT).as_posix()
                        except Exception:
                            rel_video = video_path.as_posix()
                        local_video_url = f"{base_url}/videos/{rel_video}" if rel_video else ""
                        thumb_path = out_dir / "thumbnail.jpg"
                        local_thumb_url = ""
                        try:
                            if thumb_path.exists():
                                rel_thumb = thumb_path.resolve().relative_to(GENERATED_ROOT).as_posix()
                                local_thumb_url = f"{base_url}/videos/{rel_thumb}"
                        except Exception:
                            pass

                        if IS_PRODUCTION and video_https_url:
                            post_path = video_https_url
                            video_url = video_https_url
                            thumbnail_url = thumb_https_url or local_thumb_url
                        else:
                            post_path = f"generated/{rel_video}"
                            video_url = local_video_url
                            thumbnail_url = local_thumb_url

                        # Persist user_posts (type = mlites), with optional sub_topic_id
                        dbp = Session()
                        try:
                            # Ensure required tables/columns
                            try:
                                _ensure_mlites_tables(dbp)
                                _ensure_user_posts_subtopic_column(dbp)
                            except Exception:
                                pass

                            sub_topic_id_val: Optional[int] = None
                            try:
                                # Get/create topic_id for this user/topic
                                topic_id = _get_or_create_mlites_topic_id(dbp, int(user_id), tp, int(item.get("minutes_per_day", 2)))
                                if topic_id is not None and derived_sub_topic:
                                    sub_topic_id_val = _get_or_create_mlite_sub_topic_id(dbp, int(topic_id), derived_sub_topic)
                            except Exception:
                                sub_topic_id_val = None

                            # Build stable content JSON similar to lites
                            content_json = _canonicalize_content(structured, narr, tags)

                            # Build post_topic string: "topic - subtopic" if subtopic exists, else just topic
                            try:
                                if derived_sub_topic and derived_sub_topic.strip():
                                    ptopic_val = f"{tp} - {derived_sub_topic.strip()}"
                                else:
                                    ptopic_val = tp
                            except Exception:
                                ptopic_val = tp

                            if sub_topic_id_val is not None:
                                dbp.execute(text(
                                    """
                                    INSERT INTO public.user_posts (user_id, post_path, post_topic, type, public, tags, sub_topic_id, created_on, content)
                                    VALUES (:uid, :ppath, :ptopic, 'mlites', TRUE, CAST(:tags AS JSONB), :stid, NOW(), :content)
                                    """
                                ), {
                                    "uid": int(user_id),
                                    "ppath": post_path,
                                    "ptopic": ptopic_val,
                                    "tags": json.dumps(tags or []),
                                    "stid": int(sub_topic_id_val),
                                    "content": json.dumps(content_json, ensure_ascii=False),
                                })
                                dbp.commit()
                            else:
                                dbp.execute(text(
                                    """
                                    INSERT INTO public.user_posts (user_id, post_path, post_topic, type, public, tags, created_on, content)
                                    VALUES (:uid, :ppath, :ptopic, 'mlites', TRUE, CAST(:tags AS JSONB), NOW(), :content)
                                    """
                                ), {
                                    "uid": int(user_id),
                                    "ppath": post_path,
                                    "ptopic": ptopic_val,
                                    "tags": json.dumps(tags or []),
                                    "content": json.dumps(content_json, ensure_ascii=False),
                                })
                                dbp.commit()
                        except Exception as e:
                            logger.warning(f"[mlites] persist user_posts failed: {e}")
                        finally:
                            dbp.close()

                        payload = {
                            "event": "mlite_video",
                            "topic": ptopic_val,
                            "dir": f"generated/{out_dir.name}",
                            "post_path": post_path,
                            "video_url": video_url,
                            "thumbnail_url": thumbnail_url,
                        }
                        try:
                            broker.publish_json_threadsafe(int(user_id), "mlite_video", payload)
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning(f"[mlites] post-publish failed: {e}")
        except Exception as e:
            logger.exception(f"[mlites] background error: {e}")

    ts = int(time.time())
    jobs: List[Dict[str, str]] = []
    for item in topics:
        safe = _sanitize_filename(item["topic"])
        dir_rel = f"generated/mlites_{safe}_{ts}"
        jobs.append({"topic": item["topic"], "dir": dir_rel})

    # Always pass authenticated user context to the job to ensure correct preferences (language) are used
    bg.add_task(_run, topics, getattr(current_user, "user_email", None), getattr(current_user, "user_id", None), ts)
    return {"status": "started", "message": "MLite generation started.", "count": len(topics), "jobs": jobs}

def run_mlites_for_user(user_id: int, topics: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run MLites generation inline (non-HTTP context) for a user.
    'topics' is a list of dicts with keys: topic (str), minutes_per_day (int).
    This mirrors the logic of create_mlites(), but executes synchronously so the scheduler can use it.
    """
    if not topics:
        return {"status": "skipped", "count": 0}

    ts = int(time.time())
    base_dir = _get_generated_root()
    base_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for item in topics:
        try:
            tp = (item.get("topic") or "").strip()
            if not tp:
                continue
            mpd = int(item.get("minutes_per_day", 2))

            # Ensure topic subscription row exists for this user
            try:
                dbp = Session()
                try:
                    _ensure_mlites_tables(dbp)
                    dbp.execute(text(
                        """
                        INSERT INTO public.lites_topics (user_id, topic, minutes_per_day, active)
                        VALUES (:uid, :topic, :mpd, TRUE)
                        ON CONFLICT (user_id, topic)
                        DO UPDATE SET minutes_per_day = EXCLUDED.minutes_per_day, active = TRUE, updated_on = NOW()
                        """
                    ), {"uid": int(user_id), "topic": tp, "mpd": mpd})
                    dbp.commit()
                finally:
                    dbp.close()
            except Exception as e:
                logger.warning(f"[mlites] topic upsert failed: {e}")

            # Choose a single focus subtopic for deep-dive if available
            focus_sub = None
            try:
                dbp_pick = Session()
                try:
                    focus_sub = _pick_focus_subtopic(dbp_pick, int(user_id), tp, avoid=prior_subtopics)
                finally:
                    dbp_pick.close()
            except Exception:
                focus_sub = None

            combined = f"{tp} - {focus_sub}" if (focus_sub and str(focus_sub).strip()) else tp
            safe = _sanitize_filename(combined)
            out_dir = base_dir / f"mlites_{safe}_{ts}"
            dirs = _ensure_dirs(out_dir)

            # Previous context
            prior_subtopics: Set[str] = set()
            prior_hashes: Set[str] = set()
            prior_summaries: List[str] = []
            try:
                dbp_ctx = Session()
                try:
                    prior_subtopics, prior_hashes, prior_summaries = _fetch_previous_topic_context(dbp_ctx, int(user_id), tp)
                finally:
                    dbp_ctx.close()
            except Exception:
                pass

            # Gemini mobile content generation with collision avoidance
            logger.info(f"[mlites] Generating mobile content for: {combined} (avoid {len(prior_subtopics)} subtopics, {len(prior_hashes)} hashes)")
            max_attempts = 3
            attempt = 0
            derived_sub_topic = None
            gem = {}
            while True:
                attempt += 1
                gem = _gemini_generate_mobile(tp, avoid_subtopics=list(prior_subtopics), context_summaries=prior_summaries, focus_subtopic=focus_sub)
                structured = gem.get("slides", [])
                narr = gem.get("narrations") or []
                # Translate narrations if user's preferred language is not English
                try:
                    lang_key = _resolve_user_lang_key(user_id, user_email)
                    logger.info(f"[mlites] user language key: {lang_key}")
                    narr = _maybe_translate_narrations(narr, lang_key)
                    narr = _enforce_translation(narr, lang_key)
                except Exception:
                    pass
                tags = gem.get("tags") or []
                # derive subtopic from first slide title
                derived_sub_topic = (focus_sub[:255] if (focus_sub and isinstance(focus_sub, str)) else None)
                try:
                    if not derived_sub_topic and isinstance(structured, list) and structured:
                        t0 = (structured[0].get("title") or "").strip()
                        if t0 and t0.lower() != "johnify":
                            derived_sub_topic = t0[:255]
                except Exception:
                    derived_sub_topic = None
                try:
                    if derived_sub_topic and derived_sub_topic.strip().lower() == tp.strip().lower():
                        derived_sub_topic = None
                except Exception:
                    pass
                tmp_content = _canonicalize_content(structured, narr[:len(structured)] if isinstance(narr, list) else [], tags)
                ch = tmp_content.get("content_hash") or ""
                # If focus_sub chosen, allow it even if seen before
                sub_conflict = (not focus_sub) and (derived_sub_topic and derived_sub_topic in prior_subtopics)
                hash_conflict = ch and ch in prior_hashes
                if not sub_conflict and not hash_conflict:
                    break
                logger.info(f"[mlites] collision detected (attempt {attempt}) sub_conflict={bool(sub_conflict)} hash_conflict={bool(hash_conflict)}; regenerating...")
                if attempt >= max_attempts:
                    break

            # Build markdown slides
            structured = gem.get("slides", [])
            slides: List[str] = []
            for sl in structured:
                title = (sl.get("title") or "Slide").strip()
                bullets = sl.get("bullets") or []
                bullets = [b for b in bullets if isinstance(b, str) and b.strip()]
                body = "\n".join([f"- {b.strip()}" if not b.strip().startswith('-') else b.strip() for b in bullets])
                slides.append(f"## {title}\n{body}".strip())
            narr = gem.get("narrations") or []
            if not isinstance(narr, list):
                narr = []
            if len(narr) < len(slides):
                narr.extend([f"Quick take on {combined}. Focus on the essentials."] * (len(slides) - len(narr)))
            narr = narr[:len(slides)]
            tags = gem.get("tags") or []
            try:
                (out_dir / "tags.json").write_text(json.dumps(tags, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception:
                pass

            # End card
            slides.append("## Johnify\n")
            narr.append("Thanks for watching")

            # Save slides.md
            md_file = out_dir / "slides.md"
            try:
                with md_file.open('w', encoding='utf-8') as f:
                    f.write("---\nmarp: true\ntheme: default\npaginate: true\n---\n\n")
                    for i, (s, n) in enumerate(zip(slides, narr)):
                        if i > 0:
                            f.write("\n---\n\n")
                        s = (s or "").strip()
                        if s and not any(line.strip().startswith('#') for line in s.split('\n')[:3]):
                            s = f"## Slide {i+1}\n" + s
                        # Do not auto-add placeholder bullets for reels aesthetic
                        s = '\n'.join([ln for ln in s.split('\n') if ln.strip()])
                        f.write(f"{s}\n\n<!-- NARRATION: {n} -->\n")
            except Exception as e:
                logger.error(f"[mlites] failed to write slides.md: {e}")

            # Render images
            images_dir = dirs["images"]
            try:
                # Pre-generate a shared background/thumbnail (respects MLITES_THUMBNAIL_AI/global switch)
                thumb = out_dir / "thumbnail.jpg"
                try:
                    from .main import generate_thumbnail_with_fallbacks  # type: ignore
                    if (not thumb.exists()) or (thumb.exists() and thumb.stat().st_size < 1024):
                        _ok = generate_thumbnail_with_fallbacks(tp, str(thumb), label="mlites", width=720, height=1280)
                        if not _ok:
                            # As absolute last fallback, create a plain PIL slide for background
                            _draw_text_slide(combined, "", images_dir / "_bg_tmp.png", width=1080, height=1920, mode="brand")
                            Image.open(images_dir / "_bg_tmp.png").convert('RGB').save(thumb, format='JPEG', quality=86)
                except Exception:
                    pass
                title_png = images_dir / "slide_000.png"
                _create_title_image(combined, title_png, 1080, 1920, bg_path=thumb, bg_opacity=0.2)
                raw = md_file.read_text(encoding='utf-8') if md_file.exists() else ""
                raw = raw.split('---', 2)
                content_only = raw[2] if len(raw) >= 3 else raw[0]
                blocks = [b.strip() for b in content_only.split('---') if b.strip()]
                import re as _re
                rendered = []
                for b in blocks:
                    b2 = _re.sub(r'<!--.*?-->', '', b, flags=_re.DOTALL).strip()
                    title_line = ""
                    for ln in b2.split('\n')[:3]:
                        if ln.strip().startswith('## '):
                            title_line = ln.strip()[3:].strip()
                            break
                    if not title_line:
                        title_line = "Slide"
                    body = '\n'.join([ln for ln in b2.split('\n') if not ln.strip().startswith('## ')])
                    rendered.append((title_line, body))
                for idx, (ti, body) in enumerate(rendered, 1):
                    outp = images_dir / f"slide_{idx:03d}.png"
                    is_brand_endcard = (ti.strip().lower() == "johnify") and (not (body or "").strip())
                    if is_brand_endcard:
                        _draw_text_slide(ti, body, outp, width=1080, height=1920, mode="brand")
                    else:
                        _draw_text_slide(ti, body, outp, width=1080, height=1920, bg_path=thumb, bg_opacity=0.2)
            except Exception as e:
                logger.error(f"[mlites] image render error: {e}")

            # TTS
            audio_dir = dirs["audio"]
            audio_files: List[str] = []
            image_files: List[str] = []
            try:
                # Pick voice using the SAME language key used for translation/text
                voice_choice = _pick_tts_voice_for_key(lang_key if 'lang_key' in locals() else _get_user_language_key(user_id))
                try:
                    logger.info(f"[mlites] TTS voice selected: lang={voice_choice.get('language_code')} name={voice_choice.get('name')}")
                except Exception:
                    pass
                tts_dir = _narrations_to_mp3(narr, str(audio_dir), voice_choice=voice_choice)
                audio_files = sorted([str(p) for p in Path(tts_dir).glob('*.mp3')])
                title_png = images_dir / "slide_000.png"
                if title_png.exists():
                    silent_mp3 = Path(tts_dir) / "s000.mp3"
                    if not silent_mp3.exists() or os.path.getsize(silent_mp3) == 0:
                        subprocess.run(['ffmpeg','-y','-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100','-t','1.25','-c:a','libmp3lame',str(silent_mp3)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                    audio_files = sorted([str(p) for p in Path(tts_dir).glob('*.mp3')])
            except Exception as e:
                logger.error(f"[mlites] audio generation error: {e}")

            # Pair
            try:
                image_files = sorted([str(p) for p in images_dir.glob('*.png')])
                min_len = min(len(image_files), len(audio_files))
                if min_len == 0:
                    raise ValueError("no images/audio")
                image_files = image_files[:min_len]
                audio_files = audio_files[:min_len]
            except Exception as e:
                logger.error(f"[mlites] pairing error: {e}")

            # Stitch
            video_path = out_dir / f"mlites_{safe}_{ts}.mp4"
            try:
                _stitch_images_and_audio_to_video(
                    img_dir=Path(image_files[0]).parent,
                    aud_dir=Path(audio_files[0]).parent,
                    out_mp4=video_path
                )
            except Exception as e:
                logger.error(f"[mlites] video stitch error: {e}")

            # Thumbnail
            try:
                thumb = out_dir / "thumbnail.jpg"
                if (images_dir / "slide_000.png").exists():
                    Image.open(images_dir / "slide_000.png").convert('RGB').save(thumb, format='JPEG', quality=88)
                elif image_files:
                    Image.open(image_files[0]).convert('RGB').save(thumb, format='JPEG', quality=88)
                # If still missing or too small, use unified fallbacks (Pollinations/HF/CF → PIL with centered text)
                try:
                    if (not thumb.exists()) or (thumb.exists() and thumb.stat().st_size < 1024):
                        try:
                            from .main import generate_thumbnail_with_fallbacks  # type: ignore
                            ok = generate_thumbnail_with_fallbacks(tp, str(thumb), label="mlites", width=720, height=1280)
                            if not ok:
                                raise RuntimeError("All thumbnail fallbacks failed (mlites secondary)")
                        except Exception as e2:
                            logger.warning(f"[mlites] fallback thumbnail generation failed: {e2}")
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"[mlites] thumbnail error: {e}")

            # Persist + SSE
            try:
                GENERATED_ROOT = _get_generated_root()
                ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
                IS_PRODUCTION = ENVIRONMENT == "production"
                base_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip('/')
                # Upload to GCS in production
                video_https_url = ""
                thumb_https_url = ""
                try:
                    folder = f"lites_{safe}_{ts}"
                    obj_name = f"lites_{safe}_{ts}.mp4"
                    up = maybe_upload_and_url(
                        video_path,
                        parts=["content", "lites", folder, obj_name],
                        content_type="video/mp4",
                        make_public=True,
                    )
                    video_https_url = up.get("https_url", "")
                except Exception as e:
                    logger.warning(f"[mlites] video upload skipped/failed: {e}")
                try:
                    thumb_path = out_dir / "thumbnail.jpg"
                    if thumb_path.exists():
                        thumb_obj_name = f"lites_{safe}_{ts}_thumbnail.jpg"
                        up_t = maybe_upload_and_url(
                            thumb_path,
                            parts=["content", "lites", folder, thumb_obj_name],
                            content_type="image/jpeg",
                            make_public=True,
                        )
                        thumb_https_url = up_t.get("https_url", "")
                        # Also upload a canonical copy named exactly 'thumbnail.jpg'
                        try:
                            up_t2 = maybe_upload_and_url(
                                thumb_path,
                                parts=["content", "lites", folder, "thumbnail.jpg"],
                                content_type="image/jpeg",
                                make_public=True,
                            )
                            thumb_https_url = up_t2.get("https_url", thumb_https_url)
                        except Exception as e2:
                            logger.warning(f"[mlites] secondary thumbnail.jpg upload skipped/failed: {e2}")
                except Exception as e:
                    logger.warning(f"[mlites] thumbnail upload skipped/failed: {e}")

                # Fallback to local URLs in development or on upload failure
                try:
                    rel_video = video_path.resolve().relative_to(GENERATED_ROOT).as_posix()
                except Exception:
                    rel_video = video_path.as_posix()
                local_video_url = f"{base_url}/videos/{rel_video}" if rel_video else ""
                thumb_path = out_dir / "thumbnail.jpg"
                local_thumb_url = ""
                try:
                    if thumb_path.exists():
                        rel_thumb = thumb_path.resolve().relative_to(GENERATED_ROOT).as_posix()
                        local_thumb_url = f"{base_url}/videos/{rel_thumb}"
                except Exception:
                    pass

                if IS_PRODUCTION and video_https_url:
                    post_path = video_https_url
                    video_url = video_https_url
                    thumbnail_url = thumb_https_url or local_thumb_url
                else:
                    post_path = f"generated/{rel_video}"
                    video_url = local_video_url
                    thumbnail_url = local_thumb_url

                # Persist user_posts
                dbp = Session()
                try:
                    try:
                        _ensure_mlites_tables(dbp)
                        _ensure_user_posts_subtopic_column(dbp)
                    except Exception:
                        pass
                    sub_topic_id_val: Optional[int] = None
                    try:
                        # Read-only fetch of existing topic_id to avoid a second upsert here
                        row_tid = dbp.execute(text(
                            """
                            SELECT topic_id FROM public.lites_topics
                            WHERE user_id = :uid AND topic = :topic
                            LIMIT 1
                            """
                        ), {"uid": int(user_id), "topic": tp}).mappings().first()
                        topic_id = int(row_tid["topic_id"]) if row_tid and "topic_id" in row_tid else None
                        if topic_id is not None and derived_sub_topic:
                            sub_topic_id_val = _get_or_create_mlite_sub_topic_id(dbp, int(topic_id), derived_sub_topic)
                    except Exception:
                        sub_topic_id_val = None
                    content_json = _canonicalize_content(structured, narr, tags)
                    if derived_sub_topic and derived_sub_topic.strip():
                        ptopic_val = f"{tp} - {derived_sub_topic.strip()}"
                    else:
                        ptopic_val = tp
                    if sub_topic_id_val is not None:
                        dbp.execute(text(
                            """
                            INSERT INTO public.user_posts (user_id, post_path, post_topic, type, public, tags, sub_topic_id, created_on, content)
                            VALUES (:uid, :ppath, :ptopic, 'mlites', TRUE, CAST(:tags AS JSONB), :stid, NOW(), :content)
                            """
                        ), {
                            "uid": int(user_id),
                            "ppath": post_path,
                            "ptopic": ptopic_val,
                            "tags": json.dumps(tags or []),
                            "stid": int(sub_topic_id_val),
                            "content": json.dumps(content_json, ensure_ascii=False),
                        })
                        dbp.commit()
                    else:
                        dbp.execute(text(
                            """
                            INSERT INTO public.user_posts (user_id, post_path, post_topic, type, public, tags, created_on, content)
                            VALUES (:uid, :ppath, :ptopic, 'mlites', TRUE, CAST(:tags AS JSONB), NOW(), :content)
                            """
                        ), {
                            "uid": int(user_id),
                            "ppath": post_path,
                            "ptopic": ptopic_val,
                            "tags": json.dumps(tags or []),
                            "content": json.dumps(content_json, ensure_ascii=False),
                        })
                        dbp.commit()
                finally:
                    dbp.close()

                # SSE notify
                payload = {
                    "event": "mlite_video",
                    "topic": ptopic_val,
                    "dir": f"generated/{out_dir.name}",
                    "post_path": post_path,
                    "video_url": video_url,
                    "thumbnail_url": thumbnail_url,
                }
                try:
                    broker.publish_json_threadsafe(int(user_id), "mlite_video", payload)
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"[mlites] post-publish failed: {e}")

            count += 1
        except Exception as e:
            logger.exception(f"[mlites] inline error: {e}")

    return {"status": "completed", "count": count}


# ---- Topic subscription (mirror of lites topics) ----

class MLitesTopicsUpsertItem(BaseModel):
    topic: str
    minutes_per_day: int = 2


class MLitesTopicsUpsertRequest(BaseModel):
    user_id: int
    topics: List[MLitesTopicsUpsertItem]


def _ensure_mlites_tables(db):
    """Create lites_topics and lites_sub_topics tables if not exist (idempotent)."""
    try:
        db.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.lites_topics (
                topic_id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                topic TEXT NOT NULL,
                minutes_per_day INT DEFAULT 2,
                active BOOLEAN DEFAULT TRUE,
                created_on TIMESTAMP DEFAULT NOW(),
                updated_on TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id, topic)
            );
            CREATE TABLE IF NOT EXISTS public.lites_sub_topics (
                id SERIAL PRIMARY KEY,
                topic_id INT NOT NULL,
                sub_topic TEXT NOT NULL,
                created_on TIMESTAMP DEFAULT NOW()
            );
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_lites_sub_topics_topic_subtopic'
                ) THEN
                    ALTER TABLE public.lites_sub_topics
                    ADD CONSTRAINT uq_lites_sub_topics_topic_subtopic UNIQUE (topic_id, sub_topic);
                END IF;
            END $$;
            """
        ))
        db.commit()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning(f"ensure mlites tables failed: {e}")


def _get_or_create_mlites_topic_id(db, user_id: int, topic: str, minutes_per_day: int) -> Optional[int]:
    try:
        _ensure_mlites_tables(db)
        row = db.execute(text(
            """
            INSERT INTO public.lites_topics (user_id, topic, minutes_per_day, active)
            VALUES (:uid, :topic, :mpd, TRUE)
            ON CONFLICT (user_id, topic)
            DO UPDATE SET minutes_per_day = EXCLUDED.minutes_per_day, active = TRUE, updated_on = NOW()
            RETURNING topic_id
            """
        ), {"uid": int(user_id), "topic": topic, "mpd": int(minutes_per_day)}).mappings().first()
        if row and "topic_id" in row:
            return int(row["topic_id"])  # type: ignore[index]
        row2 = db.execute(text(
            """
            SELECT topic_id FROM public.lites_topics WHERE user_id = :uid AND topic = :topic
            """
        ), {"uid": int(user_id), "topic": topic}).mappings().first()
        return int(row2["topic_id"]) if row2 and "topic_id" in row2 else None  # type: ignore[index]
    except Exception as e:
        logger.warning(f"get/create mlites_topics failed: {e}")
        return None


def _insert_mlite_sub_topic(db, topic_id: int, sub_topic: str) -> None:
    try:
        if not sub_topic:
            return
        db.execute(text(
            """
            INSERT INTO public.lites_sub_topics (topic_id, sub_topic, created_on)
            VALUES (:tid, :st, NOW())
            """
        ), {"tid": int(topic_id), "st": sub_topic})
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def _ensure_user_posts_subtopic_column(db) -> None:
    """Idempotently ensure public.user_posts has a nullable sub_topic_id column.
    Adds FK to public.lites_sub_topics(id) best-effort (ignored if fails).
    """
    try:
        # Add column if missing
        db.execute(text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='user_posts' AND column_name='sub_topic_id'
                ) THEN
                    ALTER TABLE public.user_posts ADD COLUMN sub_topic_id INT NULL;
                END IF;
            END $$;
            """
        ))
        # Try add FK constraint if not exists
        db.execute(text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints tc
                    JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
                    WHERE tc.table_schema='public' AND tc.table_name='user_posts' AND tc.constraint_type='FOREIGN KEY'
                      AND ccu.column_name='sub_topic_id'
                ) THEN
                    BEGIN
                        ALTER TABLE public.user_posts
                        ADD CONSTRAINT fk_user_posts_sub_topic
                        FOREIGN KEY (sub_topic_id) REFERENCES public.lites_sub_topics(id) ON DELETE SET NULL;
                    EXCEPTION WHEN others THEN NULL; END;
                END IF;
            END $$;
            """
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


@router.get("/topics")
async def get_mlites_topics(user_id: Optional[int] = None):
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    db = Session()
    try:
        _ensure_mlites_tables(db)
        rows = db.execute(text(
            """
            SELECT topic_id, topic, minutes_per_day, active
            FROM public.lites_topics
            WHERE user_id = :uid
            ORDER BY topic_id ASC
            """
        ), {"uid": int(user_id)}).mappings().all()
        return {"topics": [
            {
                "topic_id": r["topic_id"],
                "topic": r["topic"],
                "minutes_per_day": int(r["minutes_per_day"]),
                "active": bool(r["active"]),
            } for r in rows
        ]}
    finally:
        db.close()


@router.delete("/topics")
async def delete_mlites_topic(user_id: Optional[int] = None, topic_id: Optional[int] = None):
    if not user_id or not topic_id:
        raise HTTPException(status_code=400, detail="user_id and topic_id are required")
    db = Session()
    try:
        _ensure_mlites_tables(db)
        res = db.execute(text(
            """
            UPDATE public.lites_topics
            SET active = FALSE, updated_on = NOW()
            WHERE user_id = :uid AND topic_id = :tid
            RETURNING topic_id
            """
        ), {"uid": int(user_id), "tid": int(topic_id)}).mappings().first()
        db.commit()
        if not res:
            raise HTTPException(status_code=404, detail="Topic not found")
        return {"ok": True, "topic_id": int(res["topic_id"]) }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_mlites_topic error: {e}")
        raise HTTPException(status_code=500, detail="Failed to unsubscribe topic")
    finally:
        db.close()


@router.post("/topics")
async def upsert_mlites_topics(req: MLitesTopicsUpsertRequest):
    if not req.topics:
        raise HTTPException(status_code=400, detail="topics cannot be empty")
    allowed = {1, 2, 3, 4, 5, 10, 15}
    items: List[Dict[str, Any]] = []
    for t in req.topics[:100]:
        tp = (t.topic or "").strip()
        if not tp:
            continue
        mpd = int(t.minutes_per_day or 2)
        if mpd not in allowed:
            mpd = 2
        items.append({"topic": tp, "minutes_per_day": mpd})
    if not items:
        raise HTTPException(status_code=400, detail="all topics are empty")

    db = Session()
    try:
        _ensure_mlites_tables(db)
        for it in items:
            db.execute(text(
                """
                INSERT INTO public.lites_topics (user_id, topic, minutes_per_day, active)
                VALUES (:uid, :topic, :mpd, TRUE)
                ON CONFLICT (user_id, topic)
                DO UPDATE SET minutes_per_day = EXCLUDED.minutes_per_day, active = TRUE, updated_on = NOW()
                """
            ), {"uid": int(req.user_id), "topic": it["topic"], "mpd": int(it["minutes_per_day"])})
        db.commit()

        # Do not seed lites_sub_topics with the base topic; only subtopics should be stored.

        rows = db.execute(text(
            """
            SELECT topic_id, topic, minutes_per_day, active
            FROM public.lites_topics
            WHERE user_id = :uid
            ORDER BY topic_id ASC
            """
        ), {"uid": int(req.user_id)}).mappings().all()
        return {"topics": [
            {
                "topic_id": r["topic_id"],
                "topic": r["topic"],
                "minutes_per_day": int(r["minutes_per_day"]),
                "active": bool(r["active"]),
            } for r in rows
        ]}
    finally:
        db.close()


@router.get("/diag")
async def mlites_diag():
    def _bin_ok(name: str) -> bool:
        try:
            r = subprocess.run([name, "-version"], capture_output=True, text=True)
            return r.returncode == 0
        except Exception:
            return False
    ffmpeg_ok = _bin_ok("ffmpeg")
    ffprobe_ok = _bin_ok("ffprobe")
    gtts_ok = False
    gtts_err = None
    try:
        from google.cloud import texttospeech  # type: ignore
        _ = texttospeech.TextToSpeechClient()
        gtts_ok = True
    except Exception as e:
        gtts_err = str(e)
    if gtts_err:
        try:
            gtts_err = gtts_err.replace(os.getcwd(), "<cwd>")
        except Exception:
            pass
    return {
        "ffmpeg": ffmpeg_ok,
        "ffprobe": ffprobe_ok,
        "google_tts_client": gtts_ok,
        "google_tts_error": gtts_err,
        "env": {
            "GOOGLE_APPLICATION_CREDENTIALS": bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")),
        },
    }


@router.get("/status")
async def mlites_status(request: Request):
    try:
        query_params = request.query_params.getlist("dir") if hasattr(request, "query_params") else []
        dirs_in = [d for d in query_params if isinstance(d, str) and d.strip()]
        if not dirs_in:
            raise HTTPException(status_code=400, detail="Provide one or more 'dir' query parameters")
        ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
        IS_PRODUCTION = ENVIRONMENT == "production"
        base_root = Path("/tmp") if IS_PRODUCTION else Path(__file__).resolve().parent.parent.parent
        GENERATED_ROOT = (base_root / "generated").resolve()
        base_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip('/')
        results: List[Dict[str, Any]] = []
        for d in dirs_in:
            norm = d.replace("\\", "/").strip()
            if norm.startswith("generated/"):
                norm = norm[len("generated/"):]
            norm = norm.lstrip("/")
            abs_dir = (GENERATED_ROOT / norm).resolve()
            try:
                abs_dir.relative_to(GENERATED_ROOT)
            except Exception:
                results.append({"dir": d, "status": "invalid"})
                continue
            video_url = ""
            thumbnail_url = ""
            status = "processing"
            try:
                if abs_dir.exists() and abs_dir.is_dir():
                    mp4s = sorted([p for p in abs_dir.glob("*.mp4")])
                    if mp4s:
                        rel = mp4s[0].relative_to(GENERATED_ROOT).as_posix()
                        video_url = f"{base_url}/videos/{rel}"
                        status = "completed"
                        thumb = abs_dir / "thumbnail.jpg"
                        if thumb.exists():
                            thumb_rel = thumb.relative_to(GENERATED_ROOT).as_posix()
                            thumbnail_url = f"{base_url}/videos/{thumb_rel}"
                else:
                    status = "pending"
            except Exception as e:
                logger.warning(f"status check error for {d}: {e}")
                status = "error"
            results.append({
                "dir": d,
                "status": status,
                "video_url": video_url,
                "thumbnail_url": thumbnail_url,
            })
        return {"jobs": results}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"mlites_status error: {e}")
        raise HTTPException(status_code=500, detail="Failed to check status")


@router.get("/stream")
async def mlites_stream(user_id: Optional[int] = None):
    if user_id is None:
        raise HTTPException(status_code=400, detail="user_id is required")
    # Add standard SSE headers to avoid buffering and keep the connection alive
    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        broker.subscribe(int(user_id)),
        media_type="text/event-stream",
        headers=headers,
    )
