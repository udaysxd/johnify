from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from pathlib import Path
import os
import time
import json
import subprocess
import logging
import re
import random
import requests
import traceback
from PIL import Image, ImageDraw, ImageFont

from .auth.models import User as AuthUser
from .auth.security import get_current_user
from .database import Session
from sqlalchemy import text

# Reuse core helpers from the existing mlites pipeline
from .mlites import (
    _get_generated_root,
    _sanitize_filename,
    _ensure_dirs,
    _maybe_translate_narrations,
    _enforce_translation,
    _resolve_user_lang_key,
    _pick_tts_voice_for_key,
    _narrations_to_mp3,
    _canonicalize_content,
    _get_audio_duration,
    _create_title_image,
)
from .gcs_utils import maybe_upload_and_url
from .services.sse_broker import broker

import google.generativeai as genai
from google.cloud import texttospeech  # SSML in Books-only TTS

router = APIRouter(prefix="/api/mlites/books", tags=["mlites_books"]) 
logger = logging.getLogger("mlites_books")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] mlites_books: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ---------- Environment/FFmpeg helpers (scoped to books) ----------

def _ffmpeg_env_settings() -> Dict[str, Any]:
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
    is_prod = ENVIRONMENT == "production" or os.getenv("CLOUD_RUN", "").strip() == "1"
    width = int(os.getenv("MLITES_BOOKS_WIDTH", "1080"))
    height = int(os.getenv("MLITES_BOOKS_HEIGHT", "1920"))
    threads = int(os.getenv("MLITES_BOOKS_THREADS", "0" if not is_prod else "1"))
    preset = os.getenv("MLITES_BOOKS_PRESET", "faster" if not is_prod else "veryfast")
    crf = os.getenv("MLITES_BOOKS_CRF", "23" if not is_prod else "24")
    filter_threads = int(os.getenv("MLITES_BOOKS_FILTER_THREADS", "0" if not is_prod else "1"))
    return {
        "width": width,
        "height": height,
        "threads": threads,
        "preset": preset,
        "crf": crf,
        "filter_threads": filter_threads,
    }


def _caption_env() -> Dict[str, Any]:
    env = _ffmpeg_env_settings()
    W, H = env["width"], env["height"]
    fs_default = max(22, int(round(0.023 * H)))
    fs = int(os.getenv("MLITES_BOOKS_FONT_SIZE", str(fs_default)))
    ls_default = max(6, int(round(0.2 * fs)))
    line_spacing = int(os.getenv("MLITES_BOOKS_LINE_SPACING", str(ls_default)))
    margin_v_px_default = max(80, int(round(0.13 * H)))
    margin_v = int(os.getenv("MLITES_BOOKS_MARGIN_V", str(margin_v_px_default)))
    side_margin_default = max(40, int(round(0.06 * W)))
    side_margin = int(os.getenv("MLITES_BOOKS_SIDE_MARGIN", str(side_margin_default)))
    return {
        "font_size": fs,
        "line_spacing": line_spacing,
        "margin_v": margin_v,
        "side_margin": side_margin,
    }

# ---------- Models ----------

class BookTopic(BaseModel):
    topic: str

class CreateBooksRequest(BaseModel):
    topics: List[BookTopic]
    user_email: Optional[str] = None
    user_id: Optional[int] = None

# ---------- Stock video selection (copied pattern from beauty) ----------

def _normalize_tags(tags: Optional[List[str]]) -> List[str]:
    out: List[str] = []
    if not tags:
        return out
    for t in tags:
        if not t:
            continue
        s = str(t).strip().lower()
        if not s:
            continue
        parts = [p.strip() for p in s.split(',') if p.strip()]
        for p in parts:
            if p not in out:
                out.append(p)
    return out


def _pick_stock_video_by_topic_words(topic: str) -> Optional[str]:
    try:
        tp = (topic or "").strip()
        if not tp:
            return None
        words = [w for w in re.split(r"[^A-Za-z0-9]+", tp.lower()) if w and len(w) >= 2]
        seen = set()
        words = [w for w in words if not (w in seen or seen.add(w))]
        stopwords = {
            'the','and','a','an','of','for','to','in','on','with','from','by','at','as','is','are','be','it','its','this','that','these','those','into','over','under','up','down','out','about','but','if','or','nor','so','yet','very','than','then','also','just','more','most','too','can','will','your','you','we','our'
        }
        words = [w for w in words if w not in stopwords]
        if not words:
            return None
        dbs = Session()
        try:
            sql = text(
                """
                WITH params AS (
                    SELECT CAST(:words AS TEXT[]) AS words_param
                )
                SELECT sv.source_url,
                       (
                           SELECT COUNT(DISTINCT w.x)
                           FROM unnest((SELECT words_param FROM params)) AS w(x)
                           WHERE EXISTS (
                               SELECT 1 FROM unnest(sv.tags) AS t
                               WHERE LOWER(t) LIKE '%' || LOWER(w.x) || '%'
                           )
                       ) AS overlap
                FROM public.stock_videos sv
                WHERE sv.active = TRUE
                  AND EXISTS (
                      SELECT 1
                      FROM unnest((SELECT words_param FROM params)) AS w(x)
                      WHERE EXISTS (
                          SELECT 1 FROM unnest(sv.tags) AS t
                          WHERE LOWER(t) LIKE '%' || LOWER(w.x) || '%'
                      )
                  )
                ORDER BY overlap DESC, random()
                LIMIT 5
                """
            )
            def to_pg_array(vals: List[str]) -> str:
                esc = [v.replace('"', '\\"') for v in vals]
                return '{' + ','.join(esc) + '}'
            rows = dbs.execute(sql, {"words": to_pg_array(words)}).fetchall()
            if rows:
                import random as _rnd
                return _rnd.choice(rows)[0]
            return None
        finally:
            try:
                dbs.close()
            except Exception:
                pass
    except Exception:
        return None

def _download_to_file(url: str, dest: Path, *, connect_timeout: int = 5, read_timeout: int = 20, max_bytes: int = 50 * 1024 * 1024) -> bool:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=(connect_timeout, read_timeout)) as r:
            r.raise_for_status()
            with open(dest, 'wb') as f:
                total = 0
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
                        if total > max_bytes:
                            raise RuntimeError(f"download exceeded max {max_bytes} bytes")
        return dest.exists() and dest.stat().st_size > 0
    except Exception as e:
        logger.warning(f"[books] download failed url={url}: {e}")
        try:
            if dest.exists():
                dest.unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            pass
        return False

def _resolve_stock_video(stock: Optional[str], out_dir: Path) -> Optional[str]:
    if not stock:
        return None
    s = str(stock).strip()
    if not s:
        return None
    low = s.lower()
    if low.startswith("http://") or low.startswith("https://"):
        local = out_dir / 'stock.mp4'
        ok = _download_to_file(s, local)
        if ok:
            try:
                logger.info(f"[books] downloaded stock to {local.name} size={local.stat().st_size}")
            except Exception:
                pass
            return str(local)
        return None
    return s

def _pick_random_stock_video() -> Optional[str]:
    try:
        dbs = Session()
        try:
            rows = dbs.execute(text(
                """
                SELECT source_url
                FROM public.stock_videos
                WHERE active = TRUE
                ORDER BY random()
                LIMIT 1
                """
            )).fetchall()
            if rows:
                return rows[0][0]
            return None
        finally:
            try:
                dbs.close()
            except Exception:
                pass
    except Exception:
        return None

# ---------- Longform content generation ----------

def _gemini_generate_longform_text(topic: str) -> str:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set for Gemini")
    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_PRIMARY_MODEL", "models/gemini-2.5-flash-lite")
    model = genai.GenerativeModel(model_name)
    prompt = (
        "You are creating an audiobook-style longform summary for a short-form vertical video.\n"
        f"Topic: {topic}.\n"
        "Write a clear, engaging, non-repetitive narrative around 1800-2200 words (target ~15 minutes at ~130-150 wpm).\n"
        "Avoid headings, numbering, and markdown. Return ONLY plain text paragraphs."
    )
    resp = model.generate_content(prompt)
    text = (resp.text or "").strip()
    return text


def _split_into_sentences(text: str) -> List[str]:
    # Simple sentence splitter
    parts = re.split(r"(?<=[.!?])\s+", text.replace("\r\n", "\n").replace("\n", " ").strip())
    out = [p.strip() for p in parts if p and len(p.strip()) > 0]
    # lightly trim extremely long sentences by adding soft breaks
    cleaned: List[str] = []
    for s in out:
        if len(s) > 400:
            # break by commas as best-effort
            chunks = re.split(r",\s+", s)
            buf = []
            cur = ""
            for c in chunks:
                test = c if not cur else cur + ", " + c
                if len(test) <= 220:
                    cur = test
                else:
                    if cur:
                        buf.append(cur)
                    cur = c
            if cur:
                buf.append(cur)
            cleaned.extend([b.strip() + ("." if not b.strip().endswith(('.', '!', '?')) else "") for b in buf])
        else:
            cleaned.append(s)
    return cleaned

def _escape_ssml(text: str) -> str:
    try:
        import html
        return html.escape(text or "", quote=True)
    except Exception:
        return str(text or "")

def _to_ssml(line: str) -> str:
    """Convert a narration line to SSML with audiobook-like pacing.
    - Add a short lead-in pause
    - Replace commas/semicolons with small breaks
    - Wrap in prosody to slightly slow and soften the tone
    """
    s = _escape_ssml(str(line or "").strip())
    if not s:
        s = ""
    try:
        import re as _re
        # Light punctuation-based pauses (configurable)
        comma_ms = str(os.getenv("MLITES_BOOKS_SSML_BREAK_COMMA_MS", "200"))
        semi_ms = str(int(max(0, int(comma_ms)) + 20)) if comma_ms.isdigit() else "220"
        s = _re.sub(r"\s*,\s*", f"<break time=\"{comma_ms}ms\"/> ", s)
        s = _re.sub(r"\s*;\s*", f"<break time=\"{semi_ms}ms\"/> ", s)
    except Exception:
        pass
    rate = str(os.getenv("MLITES_BOOKS_SSML_RATE_PCT", "88"))  # % (slightly slower default)
    pitch = str(os.getenv("MLITES_BOOKS_SSML_PITCH", "-1st"))
    lead_ms = str(os.getenv("MLITES_BOOKS_SSML_BREAK_SENT_MS", "300"))
    return f"<speak><prosody rate=\"{rate}%\" pitch=\"{pitch}\"><break time=\"{lead_ms}ms\"/>{s}</prosody></speak>"

def _books_tts_to_mp3_ssml(narrations: List[str], out_dir: str, voice_choice: Optional[Dict[str, str]] = None) -> Path:
    """Books-only SSML TTS that preserves random voice selection but improves naturalness.
    Returns directory path containing sNNN.mp3 files. Falls back by raising on unrecoverable errors.
    """
    out_p = Path(out_dir)
    if out_p.exists():
        import shutil
        shutil.rmtree(out_p)
    out_p.mkdir(parents=True, exist_ok=True)

    client = texttospeech.TextToSpeechClient()
    vc_lang = (voice_choice or {}).get("language_code") or "en-US"
    vc_name = (voice_choice or {}).get("name") or "en-US-Neural2-J"
    voice = texttospeech.VoiceSelectionParams(language_code=vc_lang, name=vc_name)
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.0,
        pitch=0.0,
        sample_rate_hertz=44100,
    )
    attempts = int(os.getenv("TTS_MAX_RETRIES", "5") or "5")
    for i, narration in enumerate(narrations):
        ssml = _to_ssml(narration)
        synthesis_input = texttospeech.SynthesisInput(ssml=ssml)
        last_err: Optional[Exception] = None
        for attempt in range(1, max(1, attempts) + 1):
            _TTS_SEM.acquire()
            try:
                response = client.synthesize_speech(
                    input=synthesis_input, voice=voice, audio_config=audio_config
                )
                mp3_path = out_p / f"s{i+1:03d}.mp3"
                mp3_path.write_bytes(response.audio_content)
                last_err = None
                break
            except Exception as e:
                last_err = e
                logger.warning(f"[books] SSML TTS synth attempt {attempt} failed (voice={vc_lang}/{vc_name}): {e}")
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

def _filter_narrations(narr: List[str]) -> List[str]:
    """Remove stage-direction phrases like 'Intro music fades' but keep real content.
    - If a line contains that phrase along with other text (e.g., 'Intro music fades. Welcome to ...'),
      we strip the phrase and preserve the rest.
    - Only drop the line if nothing meaningful remains after cleanup.
    """
    try:
        import re as _re
        out: List[str] = []
        patt = _re.compile(r"\b(?:intro|introductory)\s+music\s+fades(?:\s+in\s+then\s+gently\s+out|\s+in|\s+out)?\b", _re.IGNORECASE)
        for s in narr:
            ss = str(s or "").strip()
            if not ss:
                continue
            # Remove bracketed versions like [Intro music fades] or (Intro music fades)
            ss = _re.sub(r"[\[\(]\s*(?:intro|introductory)\s+music\s+fades(?:\s+in\s+then\s+gently\s+out|\s+(?:in|out))?\s*[\]\)]", "", ss, flags=_re.IGNORECASE)
            # Remove inline phrase
            ss = patt.sub("", ss)
            # Clean leftover punctuation at start
            ss = _re.sub(r"^[\.\-:;\s]+", "", ss)
            # Normalize spaces
            ss = _re.sub(r"\s+", " ", ss).strip()
            if ss:
                out.append(ss)
        return out if out else narr
    except Exception:
        return narr

def _white_thumbnail(title: str, author: str, out_jpg: Path, width: int = None, height: int = None) -> None:
    try:
        # Read target WxH from env so thumb matches video resolution
        if width is None or height is None:
            env = _ffmpeg_env_settings()
            width = env.get("width", 1080)
            height = env.get("height", 1920)
        img = Image.new('RGB', (int(width), int(height)), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        # Pick fonts
        def _try_fonts(cands: List[str], size: int):
            for fp in cands:
                try:
                    if os.path.exists(fp):
                        return ImageFont.truetype(fp, size)
                except Exception:
                    continue
            try:
                return ImageFont.load_default()
            except Exception:
                return None
        title_font = _try_fonts([
            r"C:\\Windows\\Fonts\\segoeuib.ttf",
            r"C:\\Windows\\Fonts\\arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ], 84)
        sub_font = _try_fonts([
            r"C:\\Windows\\Fonts\\segoeui.ttf",
            r"C:\\Windows\\Fonts\\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ], 42)
        # Centered text
        def _text_size(t: str, f):
            try:
                bbox = draw.textbbox((0,0), t, font=f)
                return bbox[2]-bbox[0], bbox[3]-bbox[1]
            except Exception:
                return (len(t)*16, 40)
        t = (title or "").strip()[:140]
        a = (author or "").strip()[:140]
        tw, th = _text_size(t, title_font)
        aw, ah = _text_size(a, sub_font)
        y = height//2 - (th + (ah+16 if a else 0))//2
        tx = (width - tw)//2
        draw.text((tx, y), t, fill=(0,0,0), font=title_font)
        if a:
            y2 = y + th + 16
            ax = (width - aw)//2
            draw.text((ax, y2), a, fill=(0,0,0), font=sub_font)
        img.save(out_jpg, quality=92)
    except Exception:
        try:
            w = int(width or 1080); h = int(height or 1920)
            img = Image.new('RGB', (w, h), color=(255,255,255))
            img.save(out_jpg, quality=85)
        except Exception:
            pass


def _make_portrait_video_with_audio(stock_video: Path | str, audio_mp3: Path, out_mp4: Path, *, subtitles_path: Optional[Path] = None, drawtext_filter: Optional[str] = None) -> Path:
    env = _ffmpeg_env_settings()
    W, H = env["width"], env["height"]
    vf = f"fps=30,scale={W}:{H}:flags=fast_bilinear:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    sub_filter = None
    if subtitles_path is not None:
        # Escape Windows path
        sp = str(subtitles_path).replace('\\', r'\\').replace(':', r'\:').replace("'", "\\'")
        force_style = (
            f"FontName=Arial,FontSize=9,OutlineColour=&H80000000&,BorderStyle=3,Outline=2,Shadow=0,Alignment=2,MarginV=40"
        )
        sub_filter = f"subtitles='{sp}':force_style='{force_style}'"
    # Ensure we can loop the background: if it's a URL, try to create a local mezzanine first
    is_url = isinstance(stock_video, str) and stock_video.lower().startswith(("http://","https://"))
    local_src = None
    if is_url:
        try:
            local_src = out_mp4.parent / "bg_src.mp4"
            subprocess.run([
                "ffmpeg","-y","-i", str(stock_video),
                "-an", "-r", "30",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
                str(local_src)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            is_url = False  # we now have a local source we can loop
        except Exception:
            # Fall back to using the URL directly without looping
            local_src = None
    # Build input args: loop only when using a local file
    input_video = str(local_src) if local_src else str(stock_video)
    input_args = (["-stream_loop","-1","-i", input_video] if not is_url else ["-i", input_video])
    # Determine target duration from audio to guard against early cutoffs
    try:
        dur = float(_get_audio_duration(Path(audio_mp3)))
    except Exception:
        dur = 0.0
    vf_full = vf if (sub_filter is None and not drawtext_filter) else vf + (("," + sub_filter) if sub_filter else "") + (drawtext_filter or "")
    cmd = [
        "ffmpeg","-y",
        *input_args,
        "-i",str(audio_mp3),
        "-shortest",
        "-map","0:v:0","-map","1:a:0",
        "-c:v","libx264","-preset",str(env["preset"]),"-crf",str(env["crf"]),"-r","30",
        "-vf", vf_full,
        "-t", f"{max(0.1, dur):.2f}",
        "-aspect","9:16",
        *( ["-filter_threads", str(env["filter_threads"])] if env["filter_threads"] > 0 else [] ),
        *( ["-threads", str(env["threads"])] if env["threads"] > 0 else [] ),
        "-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","128k",
        str(out_mp4)
    ]
    try:
        # Capture stderr for diagnostics
        completed = subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        err = ""  # best-effort decode
        try:
            err = e.stderr.decode("utf-8", errors="ignore") if e.stderr else ""
        except Exception:
            pass
        raise RuntimeError(f"ffmpeg render failed: {err[:2000]}")
    return out_mp4


def _extract_thumbnail(video_path: Path, out_jpg: Path, *, title: Optional[str] = None, author: Optional[str] = None) -> None:
    try:
        if not title and not author:
            subprocess.run([
                "ffmpeg","-y","-ss","1.0","-i",str(video_path),"-frames:v","1",str(out_jpg)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return

        # Build drawtext overlay for title and author on the thumbnail frame
        def _esc(s: str) -> str:
            return s.replace('\\', r'\\').replace(':', r'\:').replace("'", "\\'")

        draw_filters = []
        if title:
            tt = _esc(title)
            draw_filters.append(
                f"drawtext=text='{tt}':fontcolor=white:fontsize=64:borderw=2:bordercolor=black:x=(w-text_w)/2:y=h*0.28:box=1:boxcolor=black@0.45:boxborderw=14"
            )
        if author:
            at = _esc(author)
            draw_filters.append(
                f"drawtext=text='{at}':fontcolor=white:fontsize=42:borderw=2:bordercolor=black:x=(w-text_w)/2:y=h*0.38:box=1:boxcolor=black@0.45:boxborderw=12"
            )
        # Ensure the thumbnail matches target WxH
        env = _ffmpeg_env_settings()
        W, H = env["width"], env["height"]
        base_vf = f"scale={W}:{H}:flags=fast_bilinear:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        vf = base_vf + ( ("," + ",".join(draw_filters)) if draw_filters else "" )

        cmd = [
            "ffmpeg","-y","-ss","1.0","-i",str(video_path),
            "-frames:v","1",
            "-vf", vf,
            str(out_jpg)
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        try:
            # Fallback to simple frame extraction
            subprocess.run([
                "ffmpeg","-y","-ss","1.0","-i",str(video_path),"-frames:v","1",str(out_jpg)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

# ---------- API ----------

@router.post("")
async def create_books(req: CreateBooksRequest, bg: BackgroundTasks, current_user: AuthUser = Depends(get_current_user)):
    if not req or not isinstance(req.topics, list) or len(req.topics) == 0:
        raise HTTPException(status_code=400, detail="At least one topic is required")

    topics: List[Dict[str, Any]] = []
    for t in req.topics[:10]:
        tp = (t.topic or "").strip()
        if not tp:
            continue
        topics.append({"topic": tp})
    if not topics:
        raise HTTPException(status_code=400, detail="All topics are empty")

    # Rate limit for books: default 5 in last 24h
    try:
        db_rl = Session()
        try:
            row = db_rl.execute(text(
                """
                SELECT COUNT(*) AS cnt
                FROM public.user_posts
                WHERE user_id = :uid
                  AND type = 'mlites_books'
                  AND created_on > NOW() - INTERVAL '24 hours'
                """
            ), {"uid": int(getattr(current_user, "user_id", 0) or 0)}).mappings().first()
            used = int(row["cnt"]) if row and row.get("cnt") is not None else 0
            limit = 20
            if used >= limit:
                raise HTTPException(status_code=429, detail=f"Daily limit reached: {limit} MLites Books in the last 24 hours. Try again later.")
            remaining = max(0, limit - used)
            if len(topics) > remaining:
                raise HTTPException(status_code=429, detail=f"Rate limit: You can create at most {remaining} more MLites Books in the next 24 hours.")
        finally:
            try:
                db_rl.close()
            except Exception:
                pass
    except HTTPException:
        raise
    except Exception:
        pass

    ts = int(time.time())

    def _run(items: List[Dict[str, Any]], user_email: Optional[str], user_id: Optional[int], ts: int):
        base_dir = _get_generated_root()
        base_dir.mkdir(parents=True, exist_ok=True)
        for item in items:
            tp = item["topic"]
            safe = _sanitize_filename(tp)
            out_dir = base_dir / f"mlites_books_{safe}_{ts}"
            dirs = _ensure_dirs(out_dir)

            # Generate longform text and split to narrations
            try:
                long_text = _gemini_generate_longform_text(tp)
            except Exception as e:
                logger.error(f"[books] longform gen failed: {e}")
                long_text = f"An introduction to {tp}. Key ideas, context, and takeaways."
            narr = _split_into_sentences(long_text)
            # Ensure non-empty
            if not narr:
                narr = [f"An introduction to {tp}.", "Key ideas, context, and takeaways."]
            # Remove unwanted lines like 'Intro music fades'
            narr = _filter_narrations(narr)

            # Language handling
            try:
                lang_key = _resolve_user_lang_key(user_id, user_email)
                narr = _maybe_translate_narrations(narr, lang_key)
                narr = _enforce_translation(narr, lang_key)
                narr = _filter_narrations(narr)
            except Exception:
                lang_key = "english"

            # TTS
            audio_dir = dirs["audio"]
            try:
                voice_choice = _pick_tts_voice_for_key(lang_key)
                # Enforce allowed English voices for Books flow
                try:
                    if isinstance(lang_key, str) and lang_key.lower().startswith("en"):
                        allowed_en_voices = {
                            "en-AU-Standard-C",
                            "en-GB-Standard-A",
                            "en-GB-Standard-B",
                            "en-GB-Standard-C",
                            "en-GB-Standard-D",
                            "en-GB-Standard-F",
                            "en-US-Standard-F",
                        }
                        if voice_choice not in allowed_en_voices:
                            voice_choice = random.choice(sorted(list(allowed_en_voices)))
                except Exception:
                    pass
                use_ssml = str(os.getenv("MLITES_BOOKS_USE_SSML", "1") or "1").strip().lower() in {"1","true","yes"}
                if use_ssml:
                    try:
                        tts_dir = _books_tts_to_mp3_ssml(narr, str(audio_dir), voice_choice=voice_choice)
                    except Exception as e_ssml:
                        logger.warning(f"[books] SSML TTS failed, falling back to plain TTS: {e_ssml}")
                        tts_dir = _narrations_to_mp3(narr, str(audio_dir), voice_choice=voice_choice)
                else:
                    tts_dir = _narrations_to_mp3(narr, str(audio_dir), voice_choice=voice_choice)
                mp3_files = sorted([p for p in Path(tts_dir).glob('*.mp3')])
            except Exception as e:
                logger.error(f"[books] audio generation error: {e}")
                mp3_files = []

            if not mp3_files:
                # 5s silent fallback
                silent = audio_dir / 's000.mp3'
                subprocess.run(['ffmpeg','-y','-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100','-t','5','-c:a','libmp3lame',str(silent)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                mp3_files = [silent]

            # Optional: slow down or speed up narration per segment to keep captions in sync
            try:
                tempo = float(os.getenv('MLITES_BOOKS_NARRATION_TEMPO', '1.0') or '1.0')
            except Exception:
                tempo = 1.0
            if abs(tempo - 1.0) > 1e-3:
                try:
                    adj_dir = out_dir / 'audio_tempo'
                    adj_dir.mkdir(exist_ok=True)
                    mp3_adj: List[Path] = []
                    # ffmpeg atempo supports 0.5..2.0; if outside, chain filters, but here we expect ~0.8
                    atempo_filter = f"atempo={max(0.5, min(2.0, tempo))}"
                    for p in mp3_files:
                        outp = adj_dir / p.name
                        subprocess.run([
                            'ffmpeg','-y','-i',str(p),
                            '-filter:a', atempo_filter,
                            '-ar','44100','-ac','2','-c:a','libmp3lame','-b:a','128k',
                            str(outp)
                        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        mp3_adj.append(outp)
                    mp3_files = mp3_adj
                    logger.info(f"[books] narration tempo adjusted with atempo={tempo} across {len(mp3_files)} segments")
                except Exception as e:
                    logger.warning(f"[books] narration tempo adjust failed, proceeding without: {e}")

            # Concatenate all narration audio
            concat_mp3 = out_dir / 'narration_full.mp3'
            list_file = out_dir / 'inputs.txt'
            with list_file.open('w', encoding='utf-8') as f:
                for p in mp3_files:
                    f.write(f"file '{p.as_posix()}'\n")
            try:
                subprocess.run([
                    'ffmpeg','-y','-f','concat','-safe','0','-i',str(list_file),
                    '-c','copy', str(concat_mp3)
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                # Re-encode fallback
                subprocess.run([
                    'ffmpeg','-y','-f','concat','-safe','0','-i',str(list_file),'-c:a','libmp3lame','-b:a','128k',str(concat_mp3)
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                logger.info(f"[books] concat built: {concat_mp3.name} size={concat_mp3.stat().st_size}")
            except Exception:
                pass

            # Build SRT captions aligned to clip durations (before any padding)
            captions_path = out_dir / 'captions.srt'
            try:
                cues: List[tuple[float, float, str]] = []
                tcur = 0.0
                for idx, p in enumerate(mp3_files):
                    dur = max(1.0, float(_get_audio_duration(Path(p))))
                    s, e = tcur, tcur + dur
                    txt = str(narr[idx]) if idx < len(narr) else ""
                    cues.append((s, e, txt))
                    tcur = e
                def _fmt(ts: float) -> str:
                    total_ms = max(0, int(round(ts * 1000)))
                    hh = total_ms // 3600000
                    mm = (total_ms % 3600000) // 60000
                    ss = (total_ms % 60000) // 1000
                    ms = total_ms % 1000
                    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"
                with captions_path.open('w', encoding='utf-8') as f:
                    for i, (s, e, txt) in enumerate(cues, 1):
                        f.write(f"{i}\n{_fmt(s)} --> {_fmt(e)}\n{txt}\n\n")
            except Exception:
                try:
                    if captions_path.exists():
                        captions_path.unlink(missing_ok=True)  # type: ignore[arg-type]
                except Exception:
                    pass
                captions_path = None  # type: ignore[assignment]

            # Ensure total duration ~ 15 min by padding silence at end if needed
            try:
                total_dur = float(_get_audio_duration(concat_mp3))
            except Exception:
                total_dur = 0.0
            target_sec = int(os.getenv("MLITES_BOOKS_TARGET_SECS", "900") or "900")
            if total_dur < target_sec - 2:
                pad = max(0, target_sec - int(total_dur))
                pad_mp3 = out_dir / 'pad.mp3'
                subprocess.run(['ffmpeg','-y','-f','lavfi','-i',f'anullsrc=channel_layout=stereo:sample_rate=44100','-t',str(pad),'-c:a','libmp3lame',str(pad_mp3)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                list2 = out_dir / 'inputs2.txt'
                with list2.open('w', encoding='utf-8') as f:
                    f.write(f"file '{concat_mp3.as_posix()}'\n")
                    f.write(f"file '{pad_mp3.as_posix()}'\n")
                concat2 = out_dir / 'narration_full_padded.mp3'
                subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(list2),'-c','copy',str(concat2)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                audio_for_video = concat2
            else:
                audio_for_video = concat_mp3
            try:
                logger.info(f"[books] audio_for_video: {audio_for_video.name} dur~{_get_audio_duration(audio_for_video)}s size={audio_for_video.stat().st_size}")
            except Exception:
                pass

            # Mix low-volume background music into the first few seconds with fade-out (Books only)
            try:
                assets_audio_dir = Path(__file__).parent / 'assets' / 'audio'
                music_candidates = []
                if assets_audio_dir.exists() and assets_audio_dir.is_dir():
                    music_candidates.extend([p for p in assets_audio_dir.iterdir() if p.suffix.lower() in {'.mp3', '.wav', '.m4a', '.aac', '.ogg'}])
                if music_candidates:
                    bgm = random.choice(music_candidates)
                    mixed_out = out_dir / 'narration_with_intro_music.mp3'
                    intro_dur = int(os.getenv('MLITES_BOOKS_INTRO_BGM_SECS', '12') or '12')
                    fade_dur = int(os.getenv('MLITES_BOOKS_INTRO_BGM_FADE_SECS', '4') or '4')
                    fade_start = max(0, intro_dur - fade_dur)
                    vol = float(os.getenv('MLITES_BOOKS_INTRO_BGM_VOL', '0.12') or '0.12')
                    # Repeat music if shorter than intro; trim to intro_dur, fade out at end
                    cmd_mix = [
                        'ffmpeg','-y',
                        '-i', str(audio_for_video),
                        '-stream_loop','-1','-i', str(bgm),
                        '-filter_complex', f"[1:a]atrim=0:{intro_dur},asetpts=N/SR/TB,volume={vol},afade=t=out:st={fade_start}:d={fade_dur}[bg];[0:a][bg]amix=inputs=2:duration=longest:dropout_transition=0",
                        '-c:a','libmp3lame','-b:a','128k',
                        str(mixed_out)
                    ]
                    subprocess.run(cmd_mix, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    audio_for_video = mixed_out
            except Exception:
                # If anything fails with BGM, fall back silently to narration-only
                pass

            # Pick stock video, else try random stock, else solid background
            allow_stock = str(os.getenv('MLITES_BOOKS_ALLOW_STOCK', '0') or '0').strip().lower() in {'1','true','yes'}
            force_solid = str(os.getenv('MLITES_BOOKS_FORCE_SOLID_BG', '0') or '0').strip().lower() in {'1','true','yes'}
            logger.info(f"[books] stock selection: allow_stock={allow_stock} force_solid={force_solid}")
            stock = None
            if allow_stock and not force_solid:
                try:
                    logger.info("[books] selecting topic-based stock...")
                    stock = _pick_stock_video_by_topic_words(tp)
                    if not stock:
                        logger.info("[books] selecting random stock...")
                        stock = _pick_random_stock_video()
                    # If we have a stock URL, download to local file for ffmpeg
                    if stock:
                        logger.info(f"[books] resolving stock: {stock}")
                        stock_resolved = _resolve_stock_video(stock, out_dir)
                        stock = stock_resolved if stock_resolved else None
                except Exception as es:
                    logger.warning(f"[books] stock selection failed: {es}")
            try:
                logger.info(f"[books] stock candidate: {stock if stock else 'solid-bg'} force_solid={force_solid}")
            except Exception:
                pass
            
            video_path = out_dir / f"mlites_books_{safe}_{ts}.mp4"
            env = _ffmpeg_env_settings()
            W, H = env["width"], env["height"]
            # Render path
            if not stock:
                # Fast inline render with lavfi color background (no captions for reliability)
                cmd_final = [
                    'ffmpeg','-y',
                    '-f','lavfi','-i',f'color=c=black:s={W}x{H}',
                    '-i', str(audio_for_video),
                    '-shortest','-map','0:v:0','-map','1:a:0',
                    '-c:v','libx264','-preset',str(env['preset']),'-crf',str(env['crf']),'-r','30',
                    '-vf', f"fps=30,scale={W}:{H}:flags=fast_bilinear:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                    '-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-movflags','+faststart',
                    str(video_path)
                ]
                logger.info("[books] inline render (solid bg, no captions)")
                try:
                    subprocess.run(cmd_final, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                except subprocess.CalledProcessError as efinal:
                    err = ''
                    try:
                        err = efinal.stderr.decode('utf-8', errors='ignore') if efinal.stderr else ''
                    except Exception:
                        pass
                    logger.error(f"[books] inline render failed: {err[:2000]}")
                    raise RuntimeError(f"books: inline render failed: {err[:400]}")
            else:
                # Prepare optional drawtext based on SRT (when we have a real stock file)
                logger.info(f"[books] rendering video: topic='{tp}' out='{video_path.name}' stock='{stock}' captions={'yes' if captions_path and captions_path.exists() else 'no'} force_solid={force_solid}")
                try:
                    _make_portrait_video_with_audio(stock, audio_for_video, video_path, subtitles_path=captions_path)
                except Exception as e1:
                    logger.warning(f"[books] render with captions failed, retrying without captions: {e1}\n{traceback.format_exc()}")
                    # Retry without captions
                    _make_portrait_video_with_audio(stock, audio_for_video, video_path, subtitles_path=None)

            if not video_path.exists() or video_path.stat().st_size <= 0:
                logger.error(f"[books] render step completed but output missing or empty: {video_path}")
                raise RuntimeError("books: render reported success but output mp4 missing")
            else:
                logger.info(f"[books] render succeeded: {video_path.name} size={video_path.stat().st_size}")

            # Thumbnail with title and author (topic format: "Book name - Author name")
            thumb = out_dir / 'thumbnail.jpg'
            try:
                parts = [p.strip() for p in str(tp).split(' - ') if p and p.strip()]
                if len(parts) >= 2:
                    book_title = parts[0]
                    author_name = parts[-1]
                else:
                    book_title = str(tp).strip()
                    author_name = ""
            except Exception:
                book_title = str(tp).strip()
                author_name = ""
            try:
                # Prefer a frame from the stock clip (no captions burned), else white fallback
                used_stock_thumb = False
                try:
                    if stock and os.path.exists(str(stock)):
                        _extract_thumbnail(Path(str(stock)), thumb, title=book_title, author=author_name)
                        used_stock_thumb = True
                except Exception:
                    used_stock_thumb = False
                if not used_stock_thumb:
                    _white_thumbnail(book_title, author_name, thumb)
                logger.info(f"[books] thumbnail saved: {thumb.name} size={thumb.stat().st_size}")
            except Exception as et:
                logger.warning(f"[books] thumbnail failed: {et}")

            # Upload
            try:
                folder = f"mlites_books_{safe}_{ts}"
                obj_name = f"mlites_books_{safe}_{ts}.mp4"
                up = maybe_upload_and_url(
                    video_path,
                    parts=["content", "mlites_books", folder, obj_name],
                    content_type="video/mp4",
                )
                video_url = up.get("https_url", str(video_path.resolve()))
            except Exception:
                video_url = str(video_path.resolve())
            try:
                if thumb.exists():
                    thumb_obj_name = f"mlites_books_{safe}_{ts}_thumbnail.jpg"
                    up_t = maybe_upload_and_url(
                        thumb,
                        parts=["content", "mlites_books", folder, thumb_obj_name],
                        content_type="image/jpeg",
                    )
                    thumb_url = up_t.get("https_url", str(thumb.resolve()))
                    # Canonical thumbnail.jpg
                    try:
                        maybe_upload_and_url(
                            thumb,
                            parts=["content", "mlites_books", folder, "thumbnail.jpg"],
                            content_type="image/jpeg",
                        )
                    except Exception:
                        pass
                else:
                    thumb_url = str(thumb.resolve())
            except Exception:
                thumb_url = str(thumb.resolve())

            # Persist post with canonical content
            tags = ["books", "summary"]
            structured = [{"title": tp, "bullets": []}]
            canon = _canonicalize_content(structured, narr[:len(structured)], tags)
            dbp = Session()
            try:
                dbp.execute(text(
                    """
                    INSERT INTO public.user_posts (user_id, post_path, post_topic, type, public, tags, created_on, content)
                    VALUES (:uid, :ppath, :ptopic, 'mlites_books', TRUE, CAST(:tags AS JSONB), NOW(), :content)
                    """
                ), {
                    "uid": int(user_id or 0),
                    "ppath": f"generated/{video_path.parent.name}",
                    "ptopic": tp,
                    "tags": json.dumps(tags),
                    "content": json.dumps(canon, ensure_ascii=False),
                })
                dbp.commit()
            except Exception as e:
                try:
                    dbp.rollback()
                except Exception:
                    pass
                logger.warning(f"[books] DB insert failed: {e}")
            finally:
                try:
                    dbp.close()
                except Exception:
                    pass

            # SSE notify
            try:
                broker.publish({
                    "type": "mlites_books_done",
                    "topic": tp,
                    "dir": str(out_dir.name),
                    "video_url": video_url,
                    "thumbnail_url": thumb_url,
                })
            except Exception:
                pass

    # Fire background job
    try:
        broker.publish({"type": "mlites_books_start", "count": len(topics)})
    except Exception:
        pass
    def _safe_run():
        try:
            _run(topics, req.user_email, req.user_id or getattr(current_user, "user_id", None), ts)
        except Exception:
            logger.error(f"[books] background _run crashed:\n{traceback.format_exc()}")
    bg.add_task(_safe_run)
    return {"ok": True, "submitted": len(topics), "ts": ts}
