from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
from pathlib import Path
import os
import time
import logging

from .auth.models import User as AuthUser
from .auth.security import get_current_user
from .gcs_utils import maybe_upload_and_url

# Reuse core helpers from mlites
from .mlites import (
    _get_generated_root,
    _sanitize_filename,
    _create_title_image,
)

router = APIRouter(prefix="/api/mlites/thumbnail", tags=["mlites_thumbnail"]) 
logger = logging.getLogger("mlites_thumbnail")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] mlites_thumbnail: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

class ThumbnailRequest(BaseModel):
    topic: str
    style: Optional[str] = None  # e.g., "Top 10", "Best 10", etc.
    language_key: Optional[str] = None  # e.g., 'english','hindi','french','italian','spanish'

class ThumbnailResponse(BaseModel):
    ok: bool
    dir: str
    filename: str
    path: str
    url: Optional[str]
    width: int
    height: int


def _generate_gemini_preview_image(prompt: str, out_path: Path, width: int = 1080, height: int = 1920) -> bool:
    """Generate an image via Google Generative Language API (Gemini image preview).
    Returns True on success. Requires GOOGLE_API_KEY.
    """
    try:
        import base64
        import requests
        from PIL import Image
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GOOGLE_API_KEY missing; cannot generate thumbnail background")
            return False
        model = "models/gemini-2.5-flash-image-preview"
        url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={api_key}"
        user_text = (
            f"Generate a single clean, aesthetic, vertical background image for the topic: {prompt}. "
            f"No text, letters, captions, logos, or watermarks. High quality, minimal, cinematic lighting. "
            f"Target size {width}x{height}."
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "generationConfig": {"temperature": 0.6},
        }
        headers = {"Content-Type": "application/json"}
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        if resp.status_code != 200:
            try:
                logger.warning(f"[thumb] Gemini preview error {resp.status_code}: {resp.text[:200]}")
            except Exception:
                logger.warning(f"[thumb] Gemini preview error {resp.status_code}")
            return False
        data = resp.json()
        image_bytes = None
        image_url = None
        for cand in (data.get("candidates") or []):
            content = (cand or {}).get("content", {})
            parts = content.get("parts") or []
            for p in parts:
                if isinstance(p, dict):
                    inline = p.get("inline_data") or p.get("inlineData")
                    if inline and isinstance(inline.get("data"), str):
                        try:
                            image_bytes = base64.b64decode(inline.get("data"))
                            break
                        except Exception:
                            pass
                    file_data = p.get("file_data") or p.get("fileData")
                    if isinstance(file_data, dict):
                        image_url = file_data.get("file_uri") or file_data.get("fileUri") or file_data.get("uri")
                        if image_url:
                            break
            if image_bytes or image_url:
                break
        if image_bytes:
            out_path.write_bytes(image_bytes)
        elif image_url:
            import requests as _rq
            r = _rq.get(image_url, timeout=30)
            r.raise_for_status()
            out_path.write_bytes(r.content)
        else:
            return False
        try:
            with Image.open(out_path) as im:
                if im.size != (width, height):
                    im = im.convert('RGB').resize((width, height), Image.LANCZOS)
                    im.save(out_path, format='JPEG', quality=86)
        except Exception:
            pass
        return out_path.exists() and out_path.stat().st_size > 1024
    except Exception as e:
        logger.warning(f"[thumb] exception generating Gemini image: {e}")
        return False


def _is_person_topic(topic: str) -> bool:
    """Heuristic: detect if topic looks like a person's name.
    - 1 to 4 words
    - avoids digits/symbols
    - words capitalized in the original input OR known famous names
    """
    try:
        raw = (topic or "").strip()
        if not raw:
            return False
        if any(ch.isdigit() for ch in raw) or any(ch in "@/#$%&_" for ch in raw):
            return False
        # Known list quick path
        known = {
            "steve jobs","alan turing","albert einstein","isaac newton","marie curie",
            "leonardo da vinci","wolfgang amadeus mozart","mozart","beethoven","bill gates",
            "elon musk","ada lovelace","grace hopper","nikola tesla","thomas edison"
        }
        low = raw.lower()
        if any(name in low for name in known):
            return True
        words = raw.split()
        if not (1 <= len(words) <= 4):
            return False
        # If majority of words start uppercase and are alphabetic, treat as person
        caps = 0
        alpha = 0
        for w in words:
            if w and w[0].isalpha():
                alpha += 1
            if w and w[0].isupper():
                caps += 1
        return alpha > 0 and caps >= max(1, len(words) - 1)
    except Exception:
        return False


def _build_prompt(topic: str, style: Optional[str]) -> str:
    t = (topic or "").strip()
    s = (style or "").strip()
    base_style = (s + " – ") if s else ""

    # Person-specific symbolic prompts to avoid realistic likenesses
    if _is_person_topic(t):
        low = t.lower()
        if "steve jobs" in low:
            return (
                base_style
                + "minimalist tech and innovation aesthetic; bright, professional, cinematic; "
                  "clean industrial design cues; soft rim-lit silhouette; muted color palette (not oversaturated); no text; vertical 1080x1920"
            )
        if "alan turing" in low:
            return (
                base_style
                + "symbolic portrait silhouette of a pioneering computer scientist; enigma/bombe rotor motifs; "
                  "chalkboard math patterns; bright, professional, cinematic; restrained emerald/teal accents; no text; vertical 1080x1920"
            )
        if "mozart" in low or "wolfgang amadeus mozart" in low:
            return (
                base_style
                + "classical music symbolism; ornate baroque flourishes; sheet music textures; violin/piano silhouette; "
                  "bright, professional, cinematic; warm golden highlights; muted elegant colors; no text; vertical 1080x1920"
            )
        # Generic person prompt
        return (
            base_style
            + f"symbolic portrait silhouette; thematic motifs relevant to {t}; elegant abstract background; "
              "no text; bright, professional, cinematic; muted, tasteful colors (not oversaturated); vertical 1080x1920"
        )

    # Non-person topics: keep concise but clear guidance
    return base_style + t + "; bright, professional, cinematic; muted, tasteful colors (not oversaturated); no text; vertical 1080x1920"


@router.post("", response_model=ThumbnailResponse)
async def create_thumbnail(req: ThumbnailRequest, current_user: Optional[AuthUser] = Depends(get_current_user)):
    topic = (req.topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail={"message": "topic is required"})

    ts = int(time.time())
    base_dir = _get_generated_root()
    base_dir.mkdir(parents=True, exist_ok=True)
    safe = _sanitize_filename(topic)
    out_dir = base_dir / f"mlites_thumbnail_{safe}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: generate a clean background via Gemini preview
    bg_jpg = out_dir / "bg.jpg"
    prompt = _build_prompt(topic, req.style)
    ok_bg = _generate_gemini_preview_image(prompt, bg_jpg, width=1080, height=1920)

    # Step 2: render final thumbnail by overlaying the title using our mlites title compositor
    thumb_jpg = out_dir / "thumbnail.jpg"
    try:
        lang_key = (req.language_key or "english").strip().lower()
    except Exception:
        lang_key = "english"
    try:
        # Light base with higher bg_opacity so generated background leads the look
        light_base = (250, 250, 250, 255)
        default_opacity = float(os.getenv("MLITES_BG_OPACITY", "0.6") or "0.6")
        _create_title_image(
            text=topic,
            out_path=thumb_jpg,
            width=1080,
            height=1920,
            bg_path=(bg_jpg if ok_bg else None),
            bg_opacity=default_opacity,
            language_key=lang_key,
            show_brand=False,
            base_color=light_base,
        )
    except Exception as e:
        logger.warning(f"[thumb] title compositor failed; fallback to plain image: {e}")
        # Minimal fallback: create a plain branded image
        try:
            from PIL import Image
            Image.new('RGB', (1080, 1920), color=(26,28,34)).save(thumb_jpg)
        except Exception:
            pass

    # Step 3: maybe upload to GCS in production
    url = None
    try:
        url = maybe_upload_and_url(thumb_jpg)
    except Exception:
        url = None

    rel = str(thumb_jpg)
    # Ensure path is returned relative to repo root when local, or gs/https when uploaded
    return ThumbnailResponse(
        ok=True,
        dir=str(out_dir),
        filename=thumb_jpg.name,
        path=str(thumb_jpg),
        url=url,
        width=1080,
        height=1920,
    )
