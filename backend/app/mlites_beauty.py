# Background opacity for Beauty image fallback (0.0 - 1.0)
try:
    _BEAUTY_BG_OPACITY = float(os.getenv("MLITES_BEAUTY_BG_OPACITY", "0.2") or "0.2")
except Exception:
    _BEAUTY_BG_OPACITY = 0.2
_BEAUTY_BG_OPACITY = max(0.0, min(1.0, _BEAUTY_BG_OPACITY))

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
import google.generativeai as genai
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from pathlib import Path
import os
import time
import json
import random
import subprocess
import logging
from PIL import Image, ImageDraw, ImageFont
import re

from .auth.models import User as AuthUser
from .auth.security import get_current_user
from .database import Session
from sqlalchemy import text

# Reuse core helpers from the existing mlites pipeline without modifying it
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
    _stitch_images_and_audio_to_video,
    _ensure_mlites_tables,
    _get_or_create_mlites_topic_id,
    _get_or_create_mlite_sub_topic_id,
)
from .gcs_utils import maybe_upload_and_url
from .services.sse_broker import broker

# Text generation via the existing mlites Gemini flow
# We import the same generator so text/narration content remains consistent
from .mlites import _gemini_generate_mobile  # type: ignore
# Creative slides helpers (for list-type topics)
try:
    from .slidegen import generate_creative_slides, get_deepseek_client  # type: ignore
except Exception:
    generate_creative_slides = None  # type: ignore[assignment]
    get_deepseek_client = None  # type: ignore[assignment]

router = APIRouter(prefix="/api/mlites/beauty", tags=["mlites_beauty"]) 
logger = logging.getLogger("mlites_beauty")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] mlites_beauty: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

def _esc_path(p: str) -> str:
    """Escape a filesystem path for use inside ffmpeg filter arguments on Windows.
    - Escape backslashes and drive colons
    - Escape single quotes because filter args are single-quoted
    """
    try:
        s = str(p or "")
        # Order matters: backslashes first
        s = s.replace('\\', r'\\')
        s = s.replace(':', r'\:')
        s = s.replace("'", r"\\'")
        return s
    except Exception:
        return str(p or "")

def _to_title_case(text: str) -> str:
    """Convert a string to title case format (each word capitalized)."""
    if not text:
        return text

    # Replace spaces, hyphens, underscores with spaces first
    text = re.sub(r'[-_\s]+', ' ', text.strip())

    # Split into words and capitalize each word
    words = text.split()
    if not words:
        return text

    # Capitalize each word
    title_case = ' '.join(word.capitalize() for word in words)

    return title_case

# Environment-aware FFmpeg tuning to reduce memory in production (Cloud Run)
def _ffmpeg_env_settings() -> dict[str, any]:
    """
    Returns a dict of encoding settings depending on environment.
    - In production, use 720x1280, fewer threads, and faster scaling to reduce memory.
    - Locally, keep 1080x1920 and default threads for quality/speed.
    You can override via env vars:
      MLITES_BEAUTY_WIDTH, MLITES_BEAUTY_HEIGHT, MLITES_BEAUTY_THREADS, MLITES_BEAUTY_PRESET, MLITES_BEAUTY_CRF
    """
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
    is_prod = ENVIRONMENT == "production" or os.getenv("CLOUD_RUN", "").strip() == "1"
    uniform = os.getenv("MLITES_BEAUTY_UNIFORM_MODE", "0").strip() == "1"
    # When uniform mode is on, default to local-style settings in all environments for reproducibility
    width = int(os.getenv("MLITES_BEAUTY_WIDTH", "1080" if uniform or not is_prod else "720"))
    height = int(os.getenv("MLITES_BEAUTY_HEIGHT", "1920" if uniform or not is_prod else "1280"))
    threads = int(os.getenv("MLITES_BEAUTY_THREADS", "0" if uniform or not is_prod else "1"))  # 0 lets ffmpeg decide
    preset = os.getenv("MLITES_BEAUTY_PRESET", "faster" if uniform or not is_prod else "veryfast")
    crf = os.getenv("MLITES_BEAUTY_CRF", "23" if uniform or not is_prod else "24")
    filter_threads = int(os.getenv("MLITES_BEAUTY_FILTER_THREADS", "0" if uniform or not is_prod else "1"))
    return {
        "is_prod": is_prod,
        "uniform": uniform,
        "width": width,
        "height": height,
        "threads": threads,
        "preset": preset,
        "crf": crf,
        "filter_threads": filter_threads,
    }


# Caption styling env (font size, spacing, margins)
def _caption_env() -> dict[str, any]:
    env = _ffmpeg_env_settings()
    is_prod = env["is_prod"]
    W, H = env["width"], env["height"]
    # Default font size scales with height (~2.3% of H; 44 @ 1920)
    fs_default = max(22, int(round(0.023 * H)))
    fs = int(os.getenv("MLITES_BEAUTY_FONT_SIZE", str(fs_default)))
    # Line spacing ~0.2 * fs
    ls_default = max(6, int(round(0.2 * fs)))
    line_spacing = int(os.getenv("MLITES_BEAUTY_LINE_SPACING", str(ls_default)))
    # Vertical margin from bottom ~13% of height
    margin_v_px_default = max(80, int(round(0.13 * H)))
    margin_v = int(os.getenv("MLITES_BEAUTY_MARGIN_V", str(margin_v_px_default)))
    # Side margin ~6% of width
    side_margin_default = max(40, int(round(0.06 * W)))
    side_margin = int(os.getenv("MLITES_BEAUTY_SIDE_MARGIN", str(side_margin_default)))
    return {
        "font_size": fs,
        "line_spacing": line_spacing,
        "margin_v": margin_v,
        "side_margin": side_margin,
    }


class BeautyTopic(BaseModel):
    topic: str
    minutes_per_day: int = 2


class CreateBeautyRequest(BaseModel):
    topics: List[BeautyTopic]
    user_email: Optional[str] = None
    user_id: Optional[int] = None


def _pick_random_template_video() -> Path:
    base = Path(__file__).resolve().parent / "assets" / "templates"
    candidates = []
    try:
        for ext in ("*.mp4", "*.mov", "*.mkv", "*.webm"):
            candidates.extend(base.glob(ext))
    except Exception:
        pass
    if not candidates:
        # Fallback: explicit known sample if directory unreadable
        p = base / "beautytips_01.mov"
        return p
    return random.choice(candidates)


def _concat_mp3s(mp3_files: List[Path], out_mp3: Path) -> Path:
    if not mp3_files:
        raise ValueError("No mp3 files to concatenate")
    tmp_dir = out_mp3.parent
    list_file = tmp_dir / "inputs.txt"
    with list_file.open("w", encoding="utf-8") as f:
        for p in mp3_files:
            f.write(f"file '{p.as_posix()}'\n")
    # Use concat demuxer; this will stream copy if codecs match
    subprocess.run([
        "ffmpeg","-y","-f","concat","-safe","0","-i",str(list_file),"-c","copy",str(out_mp3)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_mp3


def _normalize_tags(tags: Optional[List[str]]) -> list[str]:
    out: list[str] = []
    if not tags:
        return out
    for t in tags:
        if not t:
            continue
        s = str(t).strip().lower()
        if not s:
            continue
        # split comma-separated entries if needed
        parts = [p.strip() for p in s.split(',') if p.strip()]
        for p in parts:
            if p not in out:
                out.append(p)
    return out


def _infer_gender_from_tags(topic_tags: list[str]) -> Optional[str]:
    """Infer 'male' or 'female' from topic tags using common gender keywords.
    Returns 'male' | 'female' or None if no clear hint (or ambiguous)."""
    if not topic_tags:
        return None
    s = set([t.strip().lower() for t in topic_tags if t])
    female_kw = {
        'female','woman','women','lady','ladies','girl','girls','feminine','she','her','womens','women\'s','ladys','ladies\''
    }
    male_kw = {
        'male','man','men','gentleman','gentlemen','boy','boys','masculine','he','him','mens','men\'s','gentlemans'
    }
    has_f = any(k in s for k in female_kw)
    has_m = any(k in s for k in male_kw)
    if has_f and not has_m:
        return 'female'
    if has_m and not has_f:
        return 'male'
    return None


def _pick_stock_video_by_topic_words(topic: str, preferred_gender: Optional[str] = None) -> Optional[tuple[str, int]]:
    """
    Step 1: Given the user-entered topic string, split into words and search stock_videos by
    partial tag matches (ILIKE). Rank by gender match, then by number of matched words, then random().
    Returns (source_url, overlap_count) or None.
    """
    try:
        tp = (topic or "").strip()
        if not tp:
            return None
        # Split into words, normalize, dedupe, filter very short tokens
        words = [w for w in re.split(r"[^A-Za-z0-9]+", tp.lower()) if w and len(w) >= 2]
        # De-duplicate preserving order
        seen = set()
        words = [w for w in words if not (w in seen or seen.add(w))]
        # Remove common stopwords (keep domain words only)
        stopwords = {
            'the','and','a','an','of','for','to','in','on','with','from','by','at','as','is','are','be','it','its','this','that','these','those','into','over','under','up','down','out','about','but','if','or','nor','so','yet','very','than','then','also','just','more','most','too','can','will','your','you','we','our'
        }
        words = [w for w in words if w not in stopwords]
        if not words:
            return None
        # Prepare SQL that matches any tag ILIKE any of the topic words
        dbs = Session()
        try:
            sql = text(
                """
                WITH params AS (
                    SELECT CAST(:words AS TEXT[]) AS words_param,
                           :pref_gender AS pref_gender
                )
                SELECT sv.source_url,
                       (CASE WHEN sv.gender = (SELECT pref_gender FROM params) THEN 1 ELSE 0 END) AS gender_score,
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
                ORDER BY gender_score DESC, overlap DESC, random()
                LIMIT 5
                """
            )
            def to_pg_array(vals: list[str]) -> str:
                esc = [v.replace('"', '\\"') for v in vals]
                return '{' + ','.join(esc) + '}'
            res = dbs.execute(sql, {
                "words": to_pg_array(words),
                "pref_gender": (preferred_gender or '').strip().lower() or None,
            })
            rows = res.fetchall()
            if rows:
                import random as _rnd
                pick = _rnd.choice(rows)
                url = pick[0]
                overlap = int(pick[2]) if len(pick) > 2 and pick[2] is not None else 0
                try:
                    logger.info(f"[beauty] topic-words match rows={len(rows)} chosen_overlap={overlap} topic='{tp}' words={words}")
                except Exception:
                    pass
                return (url, overlap)
            return None
        finally:
            try:
                dbs.close()
            except Exception:
                pass
    except Exception as e:
        try:
            logger.warning(f"[beauty] topic-words stock selection failed; error={e}")
        except Exception:
            pass
        return None

def _pick_stock_video_by_tags(topic_tags: list[str], preferred_gender: Optional[str] = None) -> Optional[tuple[str, int]]:
    """
    Query public.stock_videos for an active stock video whose tags intersect topic_tags.
    Rank by gender match, then by overlap count, then random(). Returns source_url or None.
    """
    try:
        tags_arr = topic_tags or []
        try:
            # Diagnostic: show tag count and preview
            _preview = ','.join(tags_arr[:6])
            logger.info(f"[beauty] _pick_stock_video_by_tags: tags_count={len(tags_arr)} preview=[{_preview}] preferred_gender={preferred_gender}")
        except Exception:
            pass
        # If empty tags, skip to fallback
        if not tags_arr:
            raise RuntimeError("no topic tags")
        dbs = Session()
        try:
            # Build SQL with array param; compute overlap via ANY on casted array
            # Case-insensitive matching: compare LOWER(t) to LOWER(p.x) and avoid the case-sensitive '&&' operator
            sql = text(
                """
                WITH params AS (
                    SELECT CAST(:tags AS TEXT[]) AS tags_param,
                           :pref_gender AS pref_gender
                )
                SELECT sv.source_url,
                       (CASE WHEN sv.gender = (SELECT pref_gender FROM params) THEN 1 ELSE 0 END) AS gender_score,
                       (
                           SELECT COUNT(*)
                           FROM unnest(sv.tags) AS t
                           JOIN unnest((SELECT tags_param FROM params)) AS p(x) ON LOWER(p.x) = LOWER(t)
                       ) AS overlap
                FROM public.stock_videos sv
                WHERE sv.active = TRUE
                  AND EXISTS (
                    SELECT 1
                    FROM unnest(sv.tags) AS t
                    JOIN unnest((SELECT tags_param FROM params)) AS p(x) ON LOWER(p.x) = LOWER(t)
                  )
                ORDER BY gender_score DESC, overlap DESC, random()
                LIMIT 5
                """
            )
            # Postgres expects array input; create a literal like '{a,b}'
            def to_pg_array(vals: list[str]) -> str:
                esc = [v.replace('"', '\\"') for v in vals]
                return '{' + ','.join(esc) + '}'
            res = dbs.execute(sql, {
                "tags": to_pg_array(tags_arr),
                "pref_gender": (preferred_gender or '').strip().lower() or None,
            })
            rows = res.fetchall()
            if rows:
                import random as _rnd
                pick = _rnd.choice(rows)
                url = pick[0]
                overlap = int(pick[2]) if len(pick) > 2 and pick[2] is not None else 0
                try:
                    logger.info(f"[beauty] tag-match rows={len(rows)} chosen_overlap={overlap}")
                except Exception:
                    pass
                return (url, overlap)
            # No tag match
            return None

        finally:
            try:
                dbs.close()
            except Exception:
                pass
    except Exception as e:
        try:
            logger.warning(f"[beauty] stock video selection failed; falling back. error={e}")
        except Exception:
            pass
        return None

def _pick_stock_video_by_gender(preferred_gender: Optional[str]) -> Optional[str]:
    try:
        g = (preferred_gender or '').strip().lower()
        if not g:
            return None
        dbs = Session()
        try:
            sql = text(
                """
                SELECT sv.source_url
                FROM public.stock_videos sv
                WHERE sv.active = TRUE AND sv.gender = :g
                ORDER BY random()
                LIMIT 5
                """
            )
            rows = dbs.execute(sql, {"g": g}).fetchall()
            if rows:
                import random as _rnd
                return _rnd.choice(rows)[0]
            return None
        finally:
            dbs.close()
    except Exception as e:
        try:
            logger.warning(f"[beauty] gender-only stock selection failed: {e}")
        except Exception:
            pass
        return None


def _make_portrait_video_with_audio(stock_video: Path | str, audio_mp3: Path, out_mp4: Path, *, subtitles_path: Optional[Path] = None, drawtext_filter: Optional[str] = None, log_file: Optional[Path] = None, subtitles_font: str = "Arial", strict: bool = False) -> Path:
    # Scale/pad to portrait; loop video if shorter than audio; cut to shortest
    env = _ffmpeg_env_settings()
    W, H = env["width"], env["height"]
    vf = f"fps=30,scale={W}:{H}:flags=fast_bilinear:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    # Build subtitles filter if provided
    sub_filter = None
    if subtitles_path is not None:
        # Properly escape Windows paths for ffmpeg subtitles filter (escape \\ and :) and quotes
        sp = _esc_path(str(subtitles_path))
        # Style: bottom-centered, boxed look via libass outline
        force_style = (
            f"FontName={subtitles_font},FontSize=44,OutlineColour=&H80000000&,BorderStyle=3,Outline=2,Shadow=0,Alignment=2,MarginV=120"
        )
        sub_filter = f"subtitles='{sp}':force_style='{force_style}'"

    is_url = isinstance(stock_video, str) and stock_video.lower().startswith(("http://","https://"))
    # If remote URL, re-encode to a local mezzanine file so we can loop it reliably (handles non-seekable/chunked sources)
    local_src: Path | str = stock_video
    if is_url:
        try:
            local_src = out_mp4.parent / 'stock_src.mp4'
            subprocess.run([
                'ffmpeg','-y','-i', str(stock_video),
                '-an', '-r','30',
                '-c:v','libx264','-preset','veryfast','-crf','28','-pix_fmt','yuv420p',
                str(local_src)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            is_url = False
        except Exception:
            # If remux fails, fall back to using the URL directly without looping
            local_src = stock_video
            is_url = True
    input_args = ["-i", str(local_src)] if is_url else ["-stream_loop","-1","-i", str(local_src)]
    cmd = [
        "ffmpeg","-y",
        *input_args,
        "-i",str(audio_mp3),
        "-shortest",
        "-map","0:v:0","-map","1:a:0",
        "-c:v","libx264","-preset",str(env["preset"]),"-crf",str(env["crf"]),"-r","30",
        # Try to burn subtitles (preferred); else use any provided drawtext filter overlay
        "-vf", (
            vf if (sub_filter is None and not drawtext_filter)
            else (
                vf + (
                    ("," + sub_filter if sub_filter else '') +
                    (drawtext_filter or '')
                )
            )
        ),
        "-aspect","9:16",
        # Help ffmpeg/libass parse UTF-8 SRT on Windows
        *( ["-sub_charenc", "UTF-8"] if subtitles_path is not None else [] ),
        *( ["-filter_threads", str(env["filter_threads"])] if env["filter_threads"] > 0 else [] ),
        *( ["-threads", str(env["threads"])] if env["threads"] > 0 else [] ),
        "-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","128k",
        str(out_mp4)
    ]
    try:
        if log_file:
            with open(log_file, 'ab') as lf:
                lf.write(('\n\n=== ffmpeg (primary) ===\n' + ' '.join(cmd) + '\n').encode('utf-8', errors='ignore'))
                subprocess.run(cmd, check=True, stdout=lf, stderr=lf)
        else:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        if strict:
            # Let caller decide fallback strategy (e.g., switch to PNG overlays)
            raise
        # Retry with drawtext if available and we failed using subtitles
        if drawtext_filter and subtitles_path is not None:
            try:
                logger.warning(f"[beauty] subtitles burn failed; retrying with drawtext. Error code={e.returncode}")
                cmd_dt = [
                    "ffmpeg","-y",
                    *( ["-i", str(local_src)] if is_url else ["-stream_loop","-1","-i", str(local_src)] ),
                    "-i",str(audio_mp3),
                    "-shortest",
                    "-map","0:v:0","-map","1:a:0",
                    "-c:v","libx264","-preset",str(env["preset"]),"-crf",str(env["crf"]),"-r","30",
                    "-vf", vf + drawtext_filter,
                    *( ["-filter_threads", str(env["filter_threads"])] if env["filter_threads"] > 0 else [] ),
                    *( ["-threads", str(env["threads"])] if env["threads"] > 0 else [] ),
                    "-pix_fmt","yuv420p",
                    "-c:a","aac","-b:a","128k",
                    str(out_mp4)
                ]
                if log_file:
                    with open(log_file, 'ab') as lf:
                        lf.write(('\n\n=== ffmpeg (drawtext retry) ===\n' + ' '.join(cmd_dt) + '\n').encode('utf-8', errors='ignore'))
                        subprocess.run(cmd_dt, check=True, stdout=lf, stderr=lf)
                else:
                    subprocess.run(cmd_dt, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return out_mp4
            except subprocess.CalledProcessError as e2:
                try:
                    logger.warning(f"[beauty] drawtext burn also failed; will output without captions. Error code={e2.returncode}")
                except Exception:
                    pass
        # Retry once without any overlay
        try:
            logger.warning(f"[beauty] subtitles burn failed; retrying without subtitles. Error code={e.returncode}")
        except Exception:
            pass
        cmd_no_subs = [
            "ffmpeg","-y",
            *( ["-i", str(stock_video)] if is_url else ["-stream_loop","-1","-i", str(stock_video)] ),
            "-i",str(audio_mp3),
            "-shortest",
            "-map","0:v:0","-map","1:a:0",
            "-c:v","libx264","-preset",str(env["preset"]),"-crf",str(env["crf"]),"-r","30",
            "-vf", vf,
            "-aspect","9:16",
            *( ["-filter_threads", str(env["filter_threads"])] if env["filter_threads"] > 0 else [] ),
            *( ["-threads", str(env["threads"])] if env["threads"] > 0 else [] ),
            "-pix_fmt","yuv420p",
            "-c:a","aac","-b:a","128k",
            str(out_mp4)
        ]
        if log_file:
            with open(log_file, 'ab') as lf:
                lf.write(('\n\n=== ffmpeg (no captions retry) ===\n' + ' '.join(cmd_no_subs) + '\n').encode('utf-8', errors='ignore'))
                subprocess.run(cmd_no_subs, check=True, stdout=lf, stderr=lf)
        else:
            subprocess.run(cmd_no_subs, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_mp4


def _extract_thumbnail(video_path: Path, out_jpg: Path) -> None:
    try:
        subprocess.run([
            "ffmpeg","-y","-ss","1.0","-i",str(video_path),"-frames:v","1",str(out_jpg)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        # Non-fatal
        pass


def _find_ttf_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for fp in candidates:
        try:
            if fp and os.path.exists(fp):
                return ImageFont.truetype(fp, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _render_caption_card(text: str, out_png: Path, width: int = 1080, height: int = 1920, *, language_font_family: str = 'Arial') -> Path:
    # Transparent canvas
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Font selection
    repo_fonts = Path(__file__).resolve().parent / 'assets' / 'fonts'
    font_candidates = [
        str(repo_fonts / 'DejaVuSans.ttf'),
        str(repo_fonts / 'NotoSansDevanagari-Regular.ttf'),
        r"C:\\Windows\\Fonts\\Nirmala.ttf",
        r"C:\\Windows\\Fonts\\segoeui.ttf",
        r"C:\\Windows\\Fonts\\arial.ttf",
    ]
    font = _find_ttf_font(font_candidates, 42)
    # Sanitize and unescape common backslash-escaped sequences (e.g., \' -> ', \" -> ")
    text = (text or '').strip().replace('\r', ' ').replace('\n', ' ')
    try:
        # Unescape in a safe, ordered way
        # First reduce double backslashes
        text_unesc = text.replace('\\\\', '\\')
        # Then handle escaped quotes
        text_unesc = text_unesc.replace('\"', '"').replace("\\'", "'")
        # Finally normalize any lingering unicode-style escapes for quotes
        text = text_unesc
    except Exception:
        # Fallback to original text if anything goes wrong
        pass
    # Compute textbox area near bottom
    margin_x = 60
    box_w = width - 2 * margin_x
    # Word wrap
    def wrap_text(s: str, max_px: int) -> list[str]:
        words = s.split()
        lines: list[str] = []
        current = ''
        for w in words:
            test = w if not current else current + ' ' + w
            try:
                tw = draw.textlength(test, font=font)  # type: ignore[attr-defined]
            except Exception:
                tw = len(test) * 20
            if tw <= max_px:
                current = test
            else:
                if current:
                    lines.append(current)
                    current = w
                else:
                    lines.append(w)
                    current = ''
        if current:
            lines.append(current)
        return lines
    lines = wrap_text(text, box_w - 40)
    # Measure height
    line_h = 52
    content_h = max(line_h, len(lines) * line_h) + 40
    # Box rectangle
    box_h = content_h
    box_y = height - 260
    box_y = min(max(40, box_y), height - box_h - 40)
    box = (margin_x, box_y, width - margin_x, box_y + box_h)
    # Draw semi-opaque box
    draw.rounded_rectangle(box, radius=24, fill=(0, 0, 0, 160))
    # Draw lines centered
    y = box_y + 20
    for ln in lines:
        try:
            tw = draw.textlength(ln, font=font)  # type: ignore[attr-defined]
        except Exception:
            tw = len(ln) * 20
        x = margin_x + (box_w - int(tw)) // 2
        draw.text((x, y), ln, font=font, fill=(255, 255, 255, 245))
        y += line_h
    img.save(out_png)
    return out_png


def _make_portrait_video_with_overlays(stock_video: Path | str, audio_mp3: Path, out_mp4: Path, overlays: list[tuple[Path, float, float]], *, log_file: Optional[Path] = None) -> Path:
    # Build ffmpeg command that overlays caption PNGs conditionally by time using enable between(t,start,end)
    # Inputs: 0=stock video, 1=audio, 2..=overlay images
    env = _ffmpeg_env_settings()
    W, H = env["width"], env["height"]
    is_url = isinstance(stock_video, str) and stock_video.lower().startswith(("http://","https://"))
    # If remote URL, re-encode to a local mezzanine file so we can loop it reliably
    local_src: Path | str = stock_video
    if is_url:
        try:
            local_src = out_mp4.parent / 'stock_src.mp4'
            subprocess.run([
                'ffmpeg','-y','-i', str(stock_video),
                '-an', '-r','30',
                '-c:v','libx264','-preset','veryfast','-crf','28','-pix_fmt','yuv420p',
                str(local_src)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            is_url = False
        except Exception:
            local_src = stock_video
            is_url = True
    inputs = [
        'ffmpeg','-y',
        *( ["-i", str(local_src)] if is_url else ["-stream_loop","-1","-i", str(local_src)] ),
        '-i',str(audio_mp3),
    ]
    for (png, _s, _e) in overlays:
        inputs.extend(['-loop','1','-i',str(png)])
    # Filter complex
    vf = f"fps=30,scale={W}:{H}:flags=fast_bilinear:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    filter_chain = f"[0:v]{vf}[v0]"
    last = 'v0'
    for idx, (_png, s, e) in enumerate(overlays, start=2):
        out_lbl = f"v{idx}"
        # Center overlay image
        overlay_expr = f"[{last}][{idx}:v]overlay=(W-w)/2:(H-h)/2:enable='between(t,{s:.2f},{e:.2f})'[{out_lbl}]"
        filter_chain += f";{overlay_expr}"
        last = out_lbl
    cmd = inputs + [
        '-filter_complex', filter_chain,
        '-shortest',
        '-map', f'[{last}]', '-map', '1:a:0',
        '-c:v','libx264','-preset',str(env["preset"]),'-crf',str(env["crf"]),'-r','30',
        *( ['-filter_threads', str(env["filter_threads"])] if env["filter_threads"] > 0 else [] ),
        *( ['-threads', str(env["threads"])] if env["threads"] > 0 else [] ),
        '-pix_fmt','yuv420p',
        '-c:a','aac','-b:a','128k',
        '-aspect','9:16',
        '-movflags','+faststart',
        str(out_mp4)
    ]
    if log_file:
        with open(log_file, 'ab') as lf:
            lf.write(('\n\n=== ffmpeg (overlay path) ===\n' + ' '.join(cmd) + '\n').encode('utf-8', errors='ignore'))
            subprocess.run(cmd, check=True, stdout=lf, stderr=lf)
    else:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_mp4


@router.post("")
async def create_beauty(req: CreateBeautyRequest, bg: BackgroundTasks, current_user: AuthUser = Depends(get_current_user)):
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

    # Per-account rate limit: max 20 MLites Beauty videos in the last 24 hours
    try:
        db_rl = Session()
        try:
            row = db_rl.execute(text(
                """
                SELECT COUNT(*) AS cnt
                FROM public.user_posts
                WHERE user_id = :uid
                  AND type = 'mlites_beauty'
                  AND created_on > NOW() - INTERVAL '24 hours'
                """
            ), {"uid": int(getattr(current_user, "user_id", 0) or 0)}).mappings().first()
            used = int(row["cnt"]) if row and row.get("cnt") is not None else 0
            limit = 25
            if used >= limit:
                remaining = 0
                raise HTTPException(status_code=429, detail=f"Daily limit reached: {limit} MLites Beauty videos in the last 24 hours. Try again later.")
            # If the request attempts to exceed the remaining allowance, reject with 429 and communicate remaining
            remaining = max(0, limit - used)
            if len(topics) > remaining:
                raise HTTPException(status_code=429, detail=f"Rate limit: You can create at most {remaining} more MLites Beauty videos in the next 24 hours.")
        finally:
            try:
                db_rl.close()
            except Exception:
                pass
    except HTTPException:
        raise
    except Exception as e:
        # Fail-open if the rate limit check errors, but log it
        try:
            logger.warning(f"[beauty] Rate-limit check failed for user_id={getattr(current_user, 'user_id', None)}: {e}")
        except Exception:
            pass

    def _run(items: List[Dict[str, Any]], user_email: Optional[str], user_id: Optional[int], ts: int):
        try:
            base_dir = _get_generated_root()
            base_dir.mkdir(parents=True, exist_ok=True)
            for item in items:
                tp = item["topic"]
                # Convert topic to title case for consistent database storage
                tp_title = _to_title_case(tp)
                combined = tp_title
                safe = _sanitize_filename(combined)
                out_dir = base_dir / f"mlites_beauty_{safe}_{ts}"
                dirs = _ensure_dirs(out_dir)

                # Generate concise mobile slides/narrations via existing Gemini flow
                # Avoidance context disabled for simplicity in beauty pipeline
                #gem = _gemini_generate_mobile(tp, avoid_subtopics=[], context_summaries=[], focus_subtopic=None)
                gem = _gemini_generate_mobile(tp_title, avoid_subtopics=[], context_summaries=[], focus_subtopic=None)
                structured = gem.get("slides", [])
                narr = gem.get("narrations") or []

                # Language handling
                try:
                    lang_key = _resolve_user_lang_key(user_id, user_email)
                    narr = _maybe_translate_narrations(narr, lang_key)
                    narr = _enforce_translation(narr, lang_key)
                except Exception:
                    pass

                # Detect list-type topics (e.g., "Top 10 X", "Best 5 ...", "10 fastest cars")
                tnorm = (tp_title or "").lower()
                looks_like_list = (
                    bool(re.search(r"\b(top|best|fastest|largest|smallest|highest|biggest|longest|richest)\b", tnorm)) and bool(re.search(r"\b\d{1,3}\b", tnorm))
                ) or bool(re.search(r"\btop\s*\d{1,3}\b", tnorm)) or bool(re.search(r"^\s*\d{1,3}\s+", tnorm))

                is_list_mode = False
                list_titles: list[str] = []
                cr_slides: list[str] = []
                if looks_like_list and generate_creative_slides and get_deepseek_client:
                    try:
                        # Build creative, numbered slides and extract titles
                        client = get_deepseek_client()
                        complexity_desc = "introductory, clear"
                        cr_slides = generate_creative_slides(tp_title, complexity_desc, client, temperature=0.6) or []
                        # Parse titles from the first line of each slide
                        for s in cr_slides:
                            first = (s or "").strip().split('\n', 1)[0]
                            # Expect lines like "## 1. Item Name" or "## Item Name"
                            m = re.match(r"^##\s*(?:\d{1,3}[).:\-]?\s*)?(.+)$", first)
                            title_i = m.group(1).strip() if m else (first.replace('#', '').strip() or tp_title)
                            if title_i:
                                list_titles.append(title_i[:80])
                    except Exception as _:
                        list_titles = []
                # Fallback: if topic looks like a list but creative helpers are unavailable or returned empty,
                # try to derive list items from Gemini structured slides
                if looks_like_list and not list_titles:
                    try:
                        titles_from_struct: list[str] = []
                        for s in (structured or []):
                            if isinstance(s, dict):
                                t0 = str(s.get('title') or '').strip()
                                if t0:
                                    titles_from_struct.append(t0)
                        # Clamp to declared N if present in topic
                        mdecl_items2 = re.search(r"\b(\d{1,3})\b", (tp_title or '').lower())
                        if mdecl_items2:
                            n_target2 = int(mdecl_items2.group(1))
                            if n_target2 > 0:
                                titles_from_struct = titles_from_struct[:n_target2]
                        list_titles = [t[:80] for t in titles_from_struct if t]
                    except Exception:
                        list_titles = []
                # If we have valid list titles, switch to list-mode slides
                if list_titles:
                    is_list_mode = True
                    # Override structured slides as simple title-only entries to drive per-slide assets
                    # Prepend a title slide (video title)
                    # If topic declares a number (e.g., Top 4 ...), clamp to that many items
                    try:
                        mdecl_items = re.search(r"\b(\d{1,3})\b", (tp_title or '').lower())
                        if mdecl_items:
                            n_target = int(mdecl_items.group(1))
                            if n_target > 0:
                                list_titles = list_titles[:n_target]
                    except Exception:
                        pass
                    structured_items = [{"title": t, "bullets": []} for t in list_titles]
                    structured = ([{"title": tp_title, "bullets": []}] + structured_items)
                    # Build narrations one per slide, derived from creative slide bullets when available
                    def _extract_bullets(md_slide: str) -> list[str]:
                        try:
                            lines = (md_slide or '').replace('\r\n', '\n').split('\n')
                            bullets = []
                            for ln in lines[1:]:  # skip title line
                                l = ln.strip()
                                if not l:
                                    continue
                                if l.startswith('- '):
                                    bullets.append(l[2:].strip())
                                elif re.match(r'^\d+[).]\s+', l):
                                    bullets.append(re.sub(r'^\d+[).]\s+', '', l).strip())
                                elif l.lower().startswith('visual:'):
                                    # ignore visuals in narration
                                    continue
                            return [b for b in bullets if b][:4]
                        except Exception:
                            return []
                    narr_for_list: list[str] = []
                    # Sanitize helper to strip markdown/formatting so TTS doesn't read symbols
                    def _clean_tts(text: str) -> str:
                        try:
                            s = str(text or '')
                            # Replace image/link: ![alt](url) -> alt ; [text](url) -> text
                            s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)
                            s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
                            # Remove inline code/backticks and markdown emphasis/headers/quotes
                            s = re.sub(r"[`*_>#~]", "", s)
                            # Collapse multiple spaces
                            s = re.sub(r"\s+", " ", s).strip()
                            return s
                        except Exception:
                            return str(text)
                    # Merge 1–2 brief facts into a single, natural-sounding sentence
                    def _merge_facts_to_sentence(facts: list[str]) -> str:
                        try:
                            fs = [re.sub(r"\s+", " ", (f or "").strip()) for f in facts if str(f).strip()]
                            if not fs:
                                return "Key facts."
                            if len(fs) == 1:
                                s = fs[0].rstrip(". ") + "."
                                return s
                            # Use two facts max; join with a light connector
                            a = fs[0].rstrip(". ")
                            b = fs[1].rstrip(". ")
                            # Favor a compact joiner to keep under time
                            s = f"{a}; {b}."
                            return s
                        except Exception:
                            return "Key facts."
                    # Extract bullets from Gemini structured slides as a fallback when creative bullets are missing
                    def _extract_struct_bullets(struct_slides, title: str, idx0: int) -> list[str]:
                        try:
                            slides = struct_slides or []
                            # Prefer exact/loose title match
                            norm = lambda s: re.sub(r"\s+", " ", (s or '').strip().lower())
                            tnorm = norm(title)
                            # First try exact title match
                            for s in slides:
                                if not isinstance(s, dict):
                                    continue
                                if norm(s.get('title')) == tnorm:
                                    bs = s.get('bullets') or []
                                    return [str(b).strip() for b in bs if str(b).strip()][:3]
                            # Fallback: positional (skip title slide at 0)
                            pos = idx0  # since our list_titles starts at 1 for items, idx0 is 1-based item idx
                            if isinstance(slides, list) and len(slides) > pos:
                                bs = slides[pos].get('bullets') or [] if isinstance(slides[pos], dict) else []
                                return [str(b).strip() for b in bs if str(b).strip()][:3]
                        except Exception:
                            pass
                        return []
                    # Last-resort: generate 1-2 mini facts via Gemini when no bullets exist
                    def _generate_mini_facts_with_gemini(item_title: str, topic_title: str) -> list[str]:
                        try:
                            api_key = os.environ.get("GOOGLE_API_KEY")
                            if not api_key:
                                return []
                            genai.configure(api_key=api_key)
                            model_name = os.getenv("GEMINI_PRIMARY_MODEL", "models/gemini-2.5-flash-lite")
                            model = genai.GenerativeModel(model_name)
                            import json as _json
                            prompt = (
                                "You are generating narration facts for a short mobile video.\n"
                                "Topic: " + str(topic_title) + "\n"
                                "Item: " + str(item_title) + "\n"
                                "Return ONLY a JSON array of 2 short, simple sentences (no numbering, no asterisks, no markdown).\n"
                                "Avoid URLs and avoid extra commentary."
                            )
                            resp = model.generate_content(prompt)
                            text = (resp.text or "").strip()
                            try:
                                arr = _json.loads(text)
                            except Exception:
                                import re as _re
                                m = _re.search(r"\[[\s\S]*\]", text)
                                arr = _json.loads(m.group(0)) if m else []
                            if isinstance(arr, list) and arr:
                                out = []
                                for s in arr:
                                    s2 = str(s).strip()
                                    if s2:
                                        out.append(s2)
                                    if len(out) >= 2:
                                        break
                                return out
                            # Fallback: split by sentences
                            parts = [p.strip() for p in text.split('.') if p.strip()]
                            return [parts[0] + '.' if parts else ''][:2]
                        except Exception:
                            return []
                    # Intro narration for the title slide
                    try:
                        n_items = len(list_titles)
                        # If we can detect 'top N', announce starting rank explicitly; else start from list length
                        mdecl = re.search(r"\b(\d{1,3})\b", (tp_title or '').lower())
                        n_decl_raw = int(mdecl.group(1)) if mdecl else n_items
                        n_decl = min(max(1, n_decl_raw), n_items) if n_items else n_decl_raw
                        intro_line = f"{tp_title}. Starting at number {n_decl}."
                    except Exception:
                        intro_line = f"{tp_title}. Let's begin."
                    narr_for_list.append(_clean_tts(intro_line))
                    # Per-item narrations aligned to slide items
                    for idx, title_i in enumerate(list_titles, start=1):
                        # Descending rank number (e.g., Number 10, ... down to Number 1)
                        try:
                            n_items = len(list_titles)
                            rank_desc = max(1, n_items - (idx - 1))
                        except Exception:
                            rank_desc = idx
                        # Try to derive concise narration from corresponding creative slide
                        raw_bullets = _extract_bullets(cr_slides[idx-1]) if idx-1 < len(cr_slides) else []
                        # If creative bullets missing, fallback to Gemini structured bullets
                        if not raw_bullets:
                            raw_bullets = _extract_struct_bullets(structured, title_i, idx)
                        # Filter placeholders like 'Key fact', 'Spec', 'Fact 1', etc.
                        def _is_placeholder(s: str) -> bool:
                            t = (s or '').strip().lower()
                            if not t:
                                return True
                            bad_tokens = ['key fact', 'spec', 'placeholder', 'lorem', 'fact 1', 'fact 2', 'todo', 'n/a']
                            if any(bt in t for bt in bad_tokens):
                                return True
                            # Very short or ends with ':' likely a label
                            if len(t) < 12 or t.endswith(':'):
                                return True
                            return False
                        if raw_bullets:
                            raw_bullets = [b for b in raw_bullets if not _is_placeholder(b)]
                        if not raw_bullets:
                            raw_bullets = _generate_mini_facts_with_gemini(title_i, tp_title)
                        # Build narration with a single key-facts sentence
                        facts = [_clean_tts(b).strip() for b in raw_bullets[:2]] if raw_bullets else []
                        key_sentence = _merge_facts_to_sentence(facts)
                        sentence = f"Number {rank_desc}, {_clean_tts(title_i)}. {key_sentence}"
                        narr_for_list.append(_clean_tts(sentence))
                    # Always override narrations in list-mode to ensure alignment with slides
                    narr = narr_for_list
                    # Re-apply translation after overriding narrations
                    try:
                        narr = _maybe_translate_narrations(narr, lang_key if 'lang_key' in locals() else 'english')
                        narr = _enforce_translation(narr, lang_key if 'lang_key' in locals() else 'english')
                    except Exception:
                        pass
                else:
                    # Ensure non-empty narrations matching slides count as best-effort for non-list flow
                    if not isinstance(narr, list):
                        narr = []
                    if structured and len(narr) < len(structured):
                        narr.extend([f"Quick take on {tp}. Focus on the essentials."] * (len(structured) - len(narr)))
                    if not structured and not narr:
                        narr = [f"Quick take on {tp}. Focus on the essentials."]

                # TTS using Google Cloud, with voice chosen by user language
                audio_dir = dirs["audio"]
                try:
                    voice_choice = _pick_tts_voice_for_key(lang_key if 'lang_key' in locals() else 'english')
                    tts_dir = _narrations_to_mp3(narr, str(audio_dir), voice_choice=voice_choice)
                    mp3_files = sorted([p for p in Path(tts_dir).glob('*.mp3')])
                except Exception as e:
                    logger.error(f"[beauty] audio generation error: {e}")
                    mp3_files = []

                if not mp3_files:
                    # Generate a 5-second silent MP3 as last resort
                    silent = audio_dir / 's000.mp3'
                    subprocess.run(['ffmpeg','-y','-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100','-t','5','-c:a','libmp3lame',str(silent)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    mp3_files = [silent]

                # Concatenate all narration audio into one
                # List-mode: keep original audio frames by using concat demuxer with stream copy (no re-encode)
                if 'is_list_mode' in locals() and is_list_mode:
                    concat_mp3 = out_dir / 'narration_full.mp3'
                    list_file = out_dir / 'inputs_copy.txt'
                    with list_file.open('w', encoding='utf-8') as f:
                        for p in mp3_files:
                            f.write(f"file '{p.as_posix()}'\n")
                    subprocess.run([
                        'ffmpeg','-y','-f','concat','-safe','0','-i',str(list_file),
                        '-c','copy', str(concat_mp3)
                    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    concat_mp3 = out_dir / 'narration_full.mp3'
                    try:
                        _concat_mp3s(mp3_files, concat_mp3)
                    except Exception:
                        # If concat-copy fails, re-encode
                        list_file = out_dir / 'inputs_reencode.txt'
                        with list_file.open('w', encoding='utf-8') as f:
                            for p in mp3_files:
                                f.write(f"file '{p.as_posix()}'\n")
                        subprocess.run([
                            'ffmpeg','-y','-f','concat','-safe','0','-i',str(list_file),'-c:a','libmp3lame','-b:a','128k',str(concat_mp3)
                        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                # Build subtitles (SRT) aligned to each narration clip's duration
                captions_path = out_dir / 'captions.srt'
                try:
                    cues: List[tuple[float, float, str]] = []
                    t = 0.0
                    # Important: scope timing behavior by mode
                    # - List-mode: exact original per-clip durations (no scaling, no padding), strict chaining
                    # - Non-list: original logic (with 20s cap), no scaling, no padding
                    is_list = bool('is_list_mode' in locals() and is_list_mode)
                    for idx, p in enumerate(mp3_files):
                        dur_meas = float(_get_audio_duration(Path(p)))
                        if is_list:
                            # Exact measured durations; no scaling/padding/safety for list-mode
                            base = max(0.2, (dur_meas if dur_meas and dur_meas == dur_meas else 0.5))
                            text_line = str(narr[idx]) if idx < len(narr) else ""
                            start, end = t, t + base
                            cues.append((start, end, text_line))
                            t = end
                        else:
                            # Original non-list behavior (pre-change): include 20.0 cap, no scaling/padding
                            dur = max(1.5, min(20.0, dur_meas if dur_meas and dur_meas == dur_meas else 2.5))
                            start, end = t, t + dur
                            text_line = str(narr[idx]) if idx < len(narr) else ""
                            cues.append((start, end, text_line))
                            t = end
                    # List-mode: no end-extension; cues reflect original audio exactly
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
                    # Expose cues for potential overlays fallback later
                    try:
                        use_cues = list(cues)
                    except Exception:
                        use_cues = []
                    try:
                        logger.info(f"[beauty] built captions: cues={len(cues)} file={captions_path} size={captions_path.stat().st_size if captions_path.exists() else 0}")
                    except Exception:
                        pass
                    # Also prepare drawtext overlay filter from SRT (preferred, avoids subtitles filter)
                    # Choose a font path that likely exists (Windows/Assets/DejaVu/Noto)
                    font_candidates = [
                        # Prefer bundled font to avoid system permission/path issues
                        str(Path(__file__).resolve().parent / 'assets' / 'fonts' / 'DejaVuSans.ttf'),
                        str(Path(__file__).resolve().parent / 'assets' / 'fonts' / 'NotoSansDevanagari-Regular.ttf'),
                        # Windows fonts
                        r"C:\\Windows\\Fonts\\Nirmala.ttf",
                        r"C:\\Windows\\Fonts\\NirmalaB.ttf",
                        r"C:\\Windows\\Fonts\\Mangal.ttf",
                        r"C:\\Windows\\Fonts\\Kokila.ttf",
                        r"C:\\Windows\\Fonts\\segoeui.ttf",
                        r"C:\\Windows\\Fonts\\arial.ttf",
                    ]
                    font_path = next((p for p in font_candidates if os.path.exists(p)), None)
                    # Escape for ffmpeg drawtext (single-line variant used for overlays/png)
                    def esc_txt(t: str) -> str:
                        # Keep for potential inline drawtext usage, but when using textfile we should not escape content.
                        return t
                    # Escape and preserve newlines for drawtext
                    def esc_txt_multiline(s: str) -> str:
                        s = (s or "").replace('\r', ' ')
                        return s
                    # Pick a font family name to avoid fontfile path parsing issues on Windows
                    def has_devanagari(s: str) -> bool:
                        import re
                        return bool(re.search(r"[\u0900-\u097F]", s or ""))
                    needs_dev = False
                    try:
                        for _s in narr:
                            if has_devanagari(str(_s)):
                                needs_dev = True
                                break
                    except Exception:
                        needs_dev = False
                    font_family = 'Nirmala UI' if needs_dev else 'Arial'
                    drawtext_entries: List[str] = []
                    # Decide font spec for drawtext: prefer fontfile if available (works without fontconfig install)
                    def _esc_path(p: Optional[str]) -> str:
                        if not p:
                            return ''
                        # Escape backslashes and colons for ffmpeg filter args
                        return p.replace('\\', r'\\').replace(':', r'\:').replace("'", "\\'")
                    ff_font_spec = (
                        f"fontfile='{_esc_path(font_path)}'" if font_path else f"font='{font_family}'"
                    )
                    cap_env = _caption_env()
                    fs = cap_env["font_size"]
                    line_spacing = cap_env["line_spacing"]
                    margin_v = cap_env["margin_v"]
                    side_margin = cap_env["side_margin"]
                    # Ensure we have the target frame width/height for wrapping calculations
                    _env_dims = _ffmpeg_env_settings()
                    W = int(_env_dims.get("width", 1080))
                    H = int(_env_dims.get("height", 1920))
                    try:
                        logger.info(f"[beauty] caption settings: font={'file' if font_path else 'family'} size={fs} line_spacing={line_spacing} margin_v={margin_v} side_margin={side_margin} WxH={W}x{H}")
                    except Exception:
                        pass
                    # Rough character-per-line estimate: glyph width ~ 0.6 * font_size
                    approx_glyph_w = max(10, int(0.6 * fs))
                    usable_w = max(100, (W - 2 * side_margin))
                    max_chars = max(12, usable_w // approx_glyph_w)
                    def wrap_for_drawtext(s: str) -> str:
                        words = (s or '').split()
                        lines: list[str] = []
                        cur = ''
                        for w in words:
                            test = w if not cur else cur + ' ' + w
                            if len(test) <= max_chars:
                                cur = test
                            else:
                                if cur:
                                    lines.append(cur)
                                cur = w
                        if cur:
                            lines.append(cur)
                        # Allow more lines; configurable via env (default 10)
                        try:
                            max_lines = int(os.getenv('MLITES_BEAUTY_CAPTION_MAX_LINES', '10') or '10')
                        except Exception:
                            max_lines = 10
                        if max_lines > 0:
                            lines = lines[:max_lines]
                        return esc_txt_multiline('\n'.join(lines))
                    # Prefer to parse the actual SRT file for start/end timings
                    def _parse_ts(ts: str) -> float:
                        # Format: HH:MM:SS,mmm
                        hh, mm, rest = ts.split(':', 2)
                        ss, ms = rest.split(',', 1)
                        return int(hh) * 3600 + int(mm) * 60 + int(ss) + (int(ms) / 1000.0)
                    use_cues: List[tuple[float, float, str]] = []
                    try:
                        txt = captions_path.read_text(encoding='utf-8', errors='ignore') if captions_path.exists() else ''
                        blocks = [b for b in txt.split('\n\n') if b.strip()]
                        cues_srt: List[tuple[float, float, str]] = []
                        import re as _re
                        for b in blocks:
                            lines = [ln for ln in b.splitlines() if ln.strip()]
                            if not lines:
                                continue
                            # first line may be index; find time line
                            time_line = None
                            for ln in lines[:3]:
                                if '-->' in ln:
                                    time_line = ln
                                    break
                            if not time_line:
                                continue
                            m = _re.match(r"\s*(\d\d:\d\d:\d\d,\d\d\d)\s*-->\s*(\d\d:\d\d:\d\d,\d\d\d)", time_line)
                            if not m:
                                continue
                            s_ts, e_ts = m.group(1), m.group(2)
                            s_val, e_val = _parse_ts(s_ts), _parse_ts(e_ts)
                            # Remaining lines after the time line are text
                            text_lines = []
                            seen_time = False
                            for ln in lines:
                                if not seen_time and ln is time_line:
                                    seen_time = True
                                    continue
                                if seen_time:
                                    text_lines.append(ln)
                            # Join text lines with spaces (no escaping; textfile will read raw content)
                            text_join = ' '.join(text_lines).strip()
                            cues_srt.append((s_val, e_val, text_join))
                        # Use cues_srt if non-empty; else fallback to duration-based cues (no escaping)
                        use_cues = cues_srt if cues_srt else [(s, e, tx) for (s, e, tx) in cues]
                        # Use textfile to ensure FFmpeg processes newlines uniformly across environments
                        txt_dir = out_dir / 'captions_txt'
                        txt_dir.mkdir(exist_ok=True)
                        for (idx2, (s, e, txt_line)) in enumerate(use_cues, start=1):
                            wrapped = wrap_for_drawtext(txt_line)
                            txt_path = txt_dir / f"cap_{idx2:03d}.txt"
                            try:
                                txt_path.write_text(wrapped.replace(r"\n", "\n"), encoding='utf-8')
                            except Exception:
                                # best-effort
                                pass
                            entry = (
                                f",drawtext={ff_font_spec}:textfile='{_esc_path(str(txt_path))}':fontsize={fs}:fontcolor=white@0.98:"
                                f"line_spacing={line_spacing}:x=(w-text_w)/2:y=h-{margin_v}:box=1:boxcolor=black@0.55:boxborderw=12:"
                                f"enable='between(t,{s:.2f},{e:.2f})'"
                            )
                            drawtext_entries.append(entry)
                    except Exception:
                        # Fallback to duration-based cues if SRT parse fails
                        use_cues = [(s, e, txt) for (s, e, txt) in cues]
                        txt_dir = out_dir / 'captions_txt'
                        txt_dir.mkdir(exist_ok=True)
                        for (idx2, (s, e, txt)) in enumerate(use_cues, start=1):
                            wrapped = wrap_for_drawtext(txt)
                            txt_path = txt_dir / f"cap_{idx2:03d}.txt"
                            try:
                                txt_path.write_text(wrapped.replace(r"\n", "\n"), encoding='utf-8')
                            except Exception:
                                pass
                            entry = (
                                f",drawtext={ff_font_spec}:textfile='{_esc_path(str(txt_path))}':fontsize={fs}:fontcolor=white@0.98:"
                                f"line_spacing={line_spacing}:x=(w-text_w)/2:y=h-{margin_v}:box=1:boxcolor=black@0.55:boxborderw=12:"
                                f"enable='between(t,{s:.2f},{e:.2f})'"
                            )
                            drawtext_entries.append(entry)
                    drawtext_filter = ''.join(drawtext_entries) if drawtext_entries else None
                    if drawtext_filter:
                        try:
                            logger.info(f"[beauty] prepared drawtext overlay for {len(cues)} cues using font={font_path}")
                        except Exception:
                            pass
                except Exception:
                    try:
                        if captions_path.exists():
                            captions_path.unlink(missing_ok=True)  # type: ignore[arg-type]
                    except Exception:
                        pass
                    drawtext_filter = None

                # Choose a stock video in two steps:
                # Step 1: try topic words search against tags (partial matches)
                # Step 2: if none found, fall back to existing tag-to-tag comparison
                try:
                    tags = gem.get("tags") or []
                except Exception:
                    tags = []
                topic_tags = _normalize_tags(tags)
                # Preferred gender from env or future user profile
                preferred_gender = (os.getenv("MLITES_BEAUTY_DEFAULT_GENDER", "") or "").strip().lower() or None
                sel = _pick_stock_video_by_topic_words(tp, preferred_gender)
                if not sel:
                    sel = _pick_stock_video_by_tags(topic_tags, preferred_gender)
                stock_url = sel[0] if sel else None
                overlap_score = sel[1] if sel else -1
                images_fallback = False
                if not stock_url:
                    # Try gender-only selection ONLY if tags contain gender hints; ignore 'neutral'
                    inferred = _infer_gender_from_tags(topic_tags)
                    if inferred in ("male", "female"):
                        genders_try: list[str] = [inferred]
                        stock_url = None
                        for g in genders_try:
                            gu = _pick_stock_video_by_gender(g)
                            if gu:
                                stock_url = gu
                                preferred_gender = g
                                break
                        if not stock_url:
                            images_fallback = True
                            try:
                                logger.warning(f"[beauty] gender hinted as {inferred} but no DB video found; using image-video fallback pipeline")
                            except Exception:
                                pass
                    else:
                        # No gender hints in tags -> go straight to image-video fallback
                        images_fallback = True
                        try:
                            logger.warning(f"[beauty] no tag match and no gender hints; using image-video fallback pipeline")
                        except Exception:
                            pass
                if not images_fallback:
                    stock_video = stock_url  # type: ignore[assignment]
                    try:
                        logger.info(f"[beauty] stock selection: tags={topic_tags} gender={preferred_gender} url={stock_url} overlap={overlap_score}")
                    except Exception:
                        pass
                video_path = out_dir / f"mlites_beauty_{safe}_{ts}.mp4"
                # Persist the effective ffmpeg command used for debugging
                try:
                    ffdbg = out_dir / 'ffmpeg_cmd.txt'
                    ffdbg.write_text('drawtext_filter=' + (drawtext_filter or ''), encoding='utf-8')
                except Exception:
                    ffdbg = None

                # If images fallback OR list-mode, build slide images; list-mode uses exact-duration stitching
                if images_fallback or ('is_list_mode' in locals() and is_list_mode):
                    imgs_dir = dirs["images"]
                    try:
                        from .main import generate_thumbnail_with_fallbacks  # type: ignore
                        # Helper to reduce a title to 2-3 strong words
                        def short_overlay_text(title: str) -> str:
                            w = [x for x in re.split(r"[^A-Za-z0-9']+", (title or '').strip()) if x]
                            # Drop very short words
                            w = [x for x in w if len(x) >= 3]
                            return ' '.join(w[:3]) if w else (title or '').split(' ')[:3][0]
                        # Generate title slide background and render first slide
                        max_slides = min(len(structured) or 0, len(narr) or 0)
                        if max_slides <= 0:
                            raise RuntimeError('no slides to render')
                        # Title slide (index 1)
                        title_text_full = str(structured[0].get("title") or tp_title)
                        bg_path_title = out_dir / f"bg_000.jpg"
                        try:
                            ok_t = generate_thumbnail_with_fallbacks(title_text_full, str(bg_path_title), label="mlites_beauty_title", width=1080, height=1920)
                            if not ok_t:
                                _render_caption_card(title_text_full, imgs_dir / f"_bg_tmp_000.png", width=1080, height=1920)
                                try:
                                    Image.open(imgs_dir / f"_bg_tmp_000.png").convert('RGB').save(bg_path_title, format='JPEG', quality=86)
                                except Exception:
                                    pass
                        except Exception:
                            try:
                                _render_caption_card(title_text_full, imgs_dir / f"_bg_tmp_000.png", width=1080, height=1920)
                                Image.open(imgs_dir / f"_bg_tmp_000.png").convert('RGB').save(bg_path_title, format='JPEG', quality=86)
                            except Exception:
                                pass
                        _create_title_image(
                            title_text_full,
                            imgs_dir / f"slide_{1:03d}.png",
                            width=1080,
                            height=1920,
                            bg_path=bg_path_title if bg_path_title.exists() else None,
                            bg_opacity=_BEAUTY_BG_OPACITY,
                            language_key=(lang_key if 'lang_key' in locals() else 'english'),
                            show_brand=False,
                        )
                        # Item slides start at index 2
                        for i in range(2, max_slides + 1):
                            idx0 = i - 1  # structured index
                            title_text = str(structured[idx0].get("title") if idx0 < len(structured) and structured[idx0].get("title") else tp_title)
                            # Background per item slide
                            bg_path = out_dir / f"bg_{i:03d}.jpg"
                            try:
                                ok = generate_thumbnail_with_fallbacks(title_text, str(bg_path), label="mlites_beauty_slide", width=1080, height=1920)
                                if not ok:
                                    # Ensure some bg exists
                                    _render_caption_card(title_text, imgs_dir / f"_bg_tmp_{i:03d}.png", width=1080, height=1920)
                                    try:
                                        Image.open(imgs_dir / f"_bg_tmp_{i:03d}.png").convert('RGB').save(bg_path, format='JPEG', quality=86)
                                    except Exception:
                                        pass
                            except Exception:
                                # Best-effort fallback
                                try:
                                    _render_caption_card(title_text, imgs_dir / f"_bg_tmp_{i:03d}.png", width=1080, height=1920)
                                    Image.open(imgs_dir / f"_bg_tmp_{i:03d}.png").convert('RGB').save(bg_path, format='JPEG', quality=86)
                                except Exception:
                                    pass
                            # Render final slide with minimal overlay text (2-3 words) and descending rank prefix
                            overlay_txt = short_overlay_text(title_text)
                            try:
                                n_items = len(list_titles)
                                # item index within items (1-based) is (i-1); descending rank:
                                rank_desc = max(1, n_items - ((i - 1) - 1))  # n_items - (item_idx-1)
                                overlay_txt = f"{rank_desc}. {overlay_txt}".strip()
                            except Exception:
                                pass
                            _create_title_image(
                                overlay_txt,
                                imgs_dir / f"slide_{i:03d}.png",
                                width=1080,
                                height=1920,
                                bg_path=bg_path if bg_path.exists() else None,
                                bg_opacity=_BEAUTY_BG_OPACITY,
                                language_key=(lang_key if 'lang_key' in locals() else 'english'),
                                show_brand=False,
                            )
                        if 'is_list_mode' in locals() and is_list_mode:
                            # Build exact 90s video by padding/trimming audio per slide and stitching segments
                            try:
                                # Compute target durations summing to 90.0 seconds
                                import math
                                titles_count = max(1, len(structured))
                                narr_count = max(1, len(narr))
                                use_n = min(titles_count, narr_count)
                                # Gather original durations for the first 'use_n' mp3 files (already includes title slide narration at index 1)
                                mp3s_all = sorted([p for p in Path(audio_dir).glob('*.mp3')])
                                if len(mp3s_all) < use_n:
                                    # regenerate silent placeholders if needed
                                    while len(mp3s_all) < use_n:
                                        i_missing = len(mp3s_all) + 1
                                        silent_i = Path(audio_dir) / f's{i_missing:03d}.mp3'
                                        subprocess.run(['ffmpeg','-y','-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100','-t','2.2','-c:a','libmp3lame',str(silent_i)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                        mp3s_all.append(silent_i)
                                orig_durs = []
                                for i in range(use_n):
                                    try:
                                        d = float(_get_audio_duration(Path(mp3s_all[i])))
                                    except Exception:
                                        d = 0.0
                                    orig_durs.append(max(1.5, d if d and d == d else 2.0))
                                # Build per-slide targets close to narration length to minimize silence, but ALWAYS
                                # ensure they exceed the actual mp3 duration by a tail margin to avoid cutoffs.
                                # Title gets +0.5s, items get +0.40s baseline; penultimate/last get extra boosts.
                                min_per = 2.0
                                max_per = 16.0
                                target_total = 90.0
                                targets = []
                                for i, od in enumerate(orig_durs):
                                    margin = 0.5 if i == 0 else 0.40
                                    targets.append(max(min_per, min(max_per, od + margin)))
                                # Cap title duration hard to narration+0.5s (max 3.0s) to avoid long pause
                                try:
                                    desired_title = max(min_per, min(max_per, min(orig_durs[0] + 0.5, 3.0)))
                                    targets[0] = desired_title
                                except Exception:
                                    pass
                                # Add extra tail safety to the last (and slight to penultimate) slide to avoid mid-sentence cutoffs
                                try:
                                    if len(targets) >= 2:
                                        # +1.50s for last, +0.80s for penultimate
                                        last_i = len(targets) - 1
                                        pen_i = len(targets) - 2
                                        targets[last_i] = min(max_per, targets[last_i] + 1.50)
                                        targets[pen_i] = min(max_per, targets[pen_i] + 0.80)
                                except Exception:
                                    pass
                                # Ensure each target >= mp3_duration + per-position tail margin
                                try:
                                    for i in range(len(targets)):
                                        base_tail = 0.20 if i == 0 else 0.60
                                        if i == len(targets) - 1:
                                            base_tail = 1.50
                                        elif i == len(targets) - 2:
                                            base_tail = max(base_tail, 0.80)
                                        need = orig_durs[i] + base_tail
                                        if targets[i] < need:
                                            targets[i] = min(max_per, max(min_per, need))
                                except Exception:
                                    pass
                                # If total is under 90s, add remaining time to non-title slides only (prefer last)
                                cur_sum = sum(targets)
                                if cur_sum < target_total - 0.01:
                                    leftover = target_total - cur_sum
                                    # Add to last slide first
                                    if len(targets) >= 2:
                                        take = min(leftover, max_per - targets[-1])
                                        targets[-1] += take
                                        leftover -= take
                                    # Distribute remaining across non-title slides (1..n-1)
                                    if leftover > 0 and len(targets) > 1:
                                        non_title_idx = list(range(1, len(targets)))
                                        per = leftover / len(non_title_idx)
                                        for i in non_title_idx:
                                            add = min(per, max(0.0, max_per - targets[i]))
                                            targets[i] += add
                                        # final guard to hit exactly 90 (adjust last, not title)
                                        diff2 = target_total - sum(targets)
                                        if abs(diff2) > 0.01 and len(targets) >= 2:
                                            i_last = len(targets) - 1
                                            targets[i_last] = max(min_per, min(max_per, targets[i_last] + diff2))
                                elif cur_sum > target_total + 0.01:
                                    # If over, shrink earlier non-title slides first to preserve last slide tail safety
                                    excess = cur_sum - target_total
                                    if len(targets) > 2:
                                        # Reduce evenly across slides 1..n-2 (exclude title 0 and last)
                                        adjustable_idx = list(range(1, len(targets)-1))
                                        if adjustable_idx:
                                            per = excess / len(adjustable_idx)
                                            for i in adjustable_idx:
                                                give = min(per, max(0.0, targets[i] - min_per))
                                                targets[i] -= give
                                                excess -= give
                                    # If still excess, reduce title a bit
                                    if excess > 0 and len(targets) >= 1:
                                        give_title = min(excess, max(0.0, targets[0] - min_per))
                                        targets[0] -= give_title
                                        excess -= give_title

                                # Prepare a helper to format SRT timestamps; we'll write captions later using actual seg durations
                                def _fmt_ts(ts: float) -> str:
                                    total_ms = max(0, int(round(ts * 1000)))
                                    hh = total_ms // 3600000
                                    mm = (total_ms % 3600000) // 60000
                                    ss = (total_ms % 60000) // 1000
                                    ms = total_ms % 1000
                                    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"

                                # Use original per-slide audio durations (no padding/trimming)
                                seg_durs: list[float] = []
                                for i in range(use_n):
                                    try:
                                        dd = float(_get_audio_duration(Path(mp3s_all[i])))
                                        if not dd or dd != dd:
                                            dd = 0.0
                                    except Exception:
                                        dd = 0.0
                                    seg_durs.append(max(0.1, dd))

                                # Overwrite captions SRT to match original audio durations
                                try:
                                    tcur = 0.0
                                    with captions_path.open('w', encoding='utf-8') as f:
                                        for i in range(use_n):
                                            s = tcur
                                            e = tcur + float(seg_durs[i])
                                            text_line = str(narr[i]) if i < len(narr) else ''
                                            f.write(f"{i+1}\n{_fmt_ts(s)} --> {_fmt_ts(e)}\n{text_line}\n\n")
                                            tcur = e
                                except Exception:
                                    pass

                                # Create exact-duration segments and concatenate
                                import tempfile
                                tmp_dir = Path(tempfile.mkdtemp())
                                try:
                                    segs = []
                                    for i in range(use_n):
                                        seg = tmp_dir / f"seg_{i+1:03d}.mp4"
                                        img = sorted(Path(imgs_dir).glob('slide_*.png'))[i]
                                        mp3 = Path(mp3s_all[i])
                                        subprocess.run([
                                            'ffmpeg','-y','-loop','1','-i',str(img),'-i',str(mp3),'-shortest',
                                            '-c:v','libx264','-preset','ultrafast','-tune','stillimage','-crf','28','-r','30','-threads','1','-pix_fmt','yuv420p',
                                            '-vf','fps=30,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1',
                                            '-c:a','aac','-ar','44100','-ac','2','-b:a','128k', str(seg)
                                        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                        segs.append(seg)
                                    concat = tmp_dir / 'concat.txt'
                                    with concat.open('w', encoding='utf-8') as f:
                                        for s in segs:
                                            f.write(f"file '{s.resolve()}'\n")
                                    subprocess.run([
                                        'ffmpeg','-y','-f','concat','-safe','0','-i',str(concat),
                                        '-c:v','libx264','-preset','ultrafast','-crf','28','-r','30','-threads','1','-pix_fmt','yuv420p',
                                        '-c:a','aac','-ar','44100','-ac','2','-b:a','128k','-movflags','+faststart', str(video_path)
                                    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                finally:
                                    try:
                                        import shutil
                                        shutil.rmtree(tmp_dir, ignore_errors=True)
                                    except Exception:
                                        pass

                                # For list-mode, force PNG overlay captions to guarantee visibility (mirrors stock-video overlays)
                                try:
                                    if 'is_list_mode' in locals() and is_list_mode:
                                        overlays_img: List[tuple[Path, float, float]] = []
                                        cards_dir2 = out_dir / 'captions_png'
                                        cards_dir2.mkdir(exist_ok=True)
                                        # Build cues from existing use_cues or parse captions.srt
                                        try:
                                            cues_src = use_cues if ('use_cues' in locals() and use_cues) else []
                                        except Exception:
                                            cues_src = []
                                        if not cues_src and captions_path.exists():
                                            try:
                                                raw = captions_path.read_text(encoding='utf-8', errors='ignore')
                                                blocks = [b for b in raw.split('\n\n') if b.strip()]
                                                parsed2: list[tuple[float, float, str]] = []
                                                for b in blocks:
                                                    lines_b = [l for l in b.splitlines() if l.strip()]
                                                    if len(lines_b) < 2:
                                                        continue
                                                    timing = lines_b[1]
                                                    try:
                                                        t1, t2 = [t.strip() for t in timing.split('-->')]
                                                        def _p2(ts: str) -> float:
                                                            hh, mm, rest = ts.split(':', 2)
                                                            ss, ms = rest.split(',', 1)
                                                            return int(hh) * 3600 + int(mm) * 60 + int(ss) + (int(ms) / 1000.0)
                                                        s_val = _p2(t1)
                                                        e_val = _p2(t2)
                                                    except Exception:
                                                        continue
                                                    text_line = ' '.join(lines_b[2:]).strip()
                                                    parsed2.append((float(s_val), float(e_val), text_line))
                                                cues_src = parsed2
                                            except Exception:
                                                cues_src = []
                                        for i, (s, e, txt_line) in enumerate((cues_src or []), start=1):
                                            card_path2 = cards_dir2 / f'cap_{i:03d}.png'
                                            _render_caption_card(txt_line, card_path2, width=1080, height=1920, language_font_family=font_family)
                                            overlays_img.append((card_path2, float(s), float(e)))
                                        if overlays_img:
                                            tmp_overlay = out_dir / 'video_overlay.mp4'
                                            # Reuse overlay helper by feeding the just-produced images video as the stock input, and the exact concatenated audio
                                            _make_portrait_video_with_overlays(str(video_path), concat_mp3, tmp_overlay, overlays_img, log_file=ffdbg)
                                            try:
                                                video_path.unlink(missing_ok=True)  # type: ignore[arg-type]
                                            except Exception:
                                                pass
                                            tmp_overlay.rename(video_path)
                                    else:
                                        # Non-list: keep existing subtitles burn (no change)
                                        if captions_path.exists():
                                            env = _ffmpeg_env_settings()
                                            tmp_burn = out_dir / 'video_burn.mp4'
                                            sp = _esc_path(str(captions_path))
                                            subprocess.run([
                                                'ffmpeg','-y','-i',str(video_path),
                                                '-vf', f"subtitles='{sp}':force_style='FontName=Arial,FontSize=44,OutlineColour=&H80000000&,BorderStyle=3,Outline=2,Shadow=0,Alignment=2,MarginV=120'",
                                                '-c:v','libx264','-preset',str(env['preset']),'-crf',str(env['crf']),'-r','30',
                                                '-c:a','copy', str(tmp_burn)
                                            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                            try:
                                                video_path.unlink(missing_ok=True)  # type: ignore[arg-type]
                                            except Exception:
                                                pass
                                            tmp_burn.rename(video_path)
                                except Exception:
                                    pass
                            except Exception as _exact_err:
                                logger.warning(f"[beauty] exact-90 stitching failed; falling back to standard stitch. err={_exact_err}")
                                _stitch_images_and_audio_to_video(imgs_dir, audio_dir, video_path)
                        else:
                            # Non-list images fallback retains the standard stitcher
                            _stitch_images_and_audio_to_video(imgs_dir, audio_dir, video_path)
                        
                    except Exception as _img_err:
                        logger.warning(f"[beauty] image-video fallback failed: {_img_err}")
                        # Skip this topic on failure
                        continue
                # Else choose caption rendering mode for stock video path: prefer drawtext in production to minimize memory
                else:
                    ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
                    is_prod = ENVIRONMENT == "production" or os.getenv("CLOUD_RUN", "").strip() == "1"
                    caption_mode = os.getenv("MLITES_BEAUTY_CAPTION_MODE", "drawtext" if is_prod else "overlays").lower()
                    # For list-type, FORCE overlays to guarantee captions display
                    try:
                        if is_list_mode:
                            caption_mode = "overlays"
                    except Exception:
                        pass
                    if caption_mode == "overlays":
                        # Preferred locally: image overlay captions
                        try:
                            overlays: List[tuple[Path, float, float]] = []
                            cards_dir = out_dir / 'captions_png'
                            cards_dir.mkdir(exist_ok=True)
                            # Add a short visibility test card at the very beginning
                            try:
                                env_xy = _ffmpeg_env_settings(); W, H = env_xy["width"], env_xy["height"]
                                test_card = cards_dir / 'cap_test.png'
                                _render_caption_card('CAPTION TEST', test_card, width=W, height=H, language_font_family=font_family)
                                overlays.append((test_card, 0.0, 2.0))
                            except Exception:
                                pass
                            # If use_cues is empty or undefined, build cues from captions.srt
                            try:
                                has_cues = ('use_cues' in locals()) and bool(use_cues)
                            except Exception:
                                has_cues = False
                            if not has_cues and captions_path.exists():
                                try:
                                    raw = captions_path.read_text(encoding='utf-8', errors='ignore')
                                    blocks = [b for b in raw.split('\n\n') if b.strip()]
                                    parsed: list[tuple[float, float, str]] = []
                                    for b in blocks:
                                        lines_b = [l for l in b.splitlines() if l.strip()]
                                        if len(lines_b) < 2:
                                            continue
                                        # timing line is typically the second line
                                        timing = lines_b[1]
                                        # parse HH:MM:SS,ms --> HH:MM:SS,ms
                                        try:
                                            t1, t2 = [t.strip() for t in timing.split('-->')]
                                            def _p(ts: str) -> float:
                                                hh, mm, rest = ts.split(':', 2)
                                                ss, ms = rest.split(',', 1)
                                                return int(hh) * 3600 + int(mm) * 60 + int(ss) + (int(ms) / 1000.0)
                                            s_val = _p(t1)
                                            e_val = _p(t2)
                                        except Exception:
                                            continue
                                        text_line = ' '.join(lines_b[2:]).strip()
                                        parsed.append((float(s_val), float(e_val), text_line))
                                    if parsed:
                                        try:
                                            use_cues = parsed
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                            for i, (s, e, txt_line) in enumerate((use_cues or []), start=1):
                                env_xy = _ffmpeg_env_settings(); W, H = env_xy["width"], env_xy["height"]
                                card_path = cards_dir / f'cap_{i:03d}.png'
                                _render_caption_card(txt_line, card_path, width=W, height=H, language_font_family=font_family)
                                overlays.append((card_path, float(s), float(e)))
                            if overlays:
                                _make_portrait_video_with_overlays(stock_video, concat_mp3, video_path, overlays, log_file=ffdbg)
                            else:
                                raise RuntimeError('no overlays built')
                        except Exception as _ov_err:
                            # Fallback to subtitles/drawtext path
                            _make_portrait_video_with_audio(
                                stock_video, concat_mp3, video_path,
                                subtitles_path=captions_path if captions_path.exists() else None,
                                drawtext_filter=drawtext_filter,
                                log_file=ffdbg,
                                subtitles_font=font_family
                            )
                    else:
                        # Production default: single-pass drawtext (lower memory than multi-input overlays)
                        try:
                            # For list-mode, use the same drawtext-only approach as non-list
                            _make_portrait_video_with_audio(
                                stock_video, concat_mp3, video_path,
                                subtitles_path=None,
                                drawtext_filter=drawtext_filter,
                                log_file=ffdbg,
                                subtitles_font=font_family,
                                strict=True,
                            )
                        except Exception as _dt_err:
                            # Fallback to PNG overlay captions to handle intermittent drawtext failures
                            try:
                                overlays: List[tuple[Path, float, float]] = []
                                cards_dir = out_dir / 'captions_png'
                                cards_dir.mkdir(exist_ok=True)
                                for i, (s, e, txt_line) in enumerate(use_cues or [], start=1):
                                    env_xy = _ffmpeg_env_settings(); W, H = env_xy["width"], env_xy["height"]
                                    card_path = cards_dir / f'cap_{i:03d}.png'
                                    _render_caption_card(txt_line, card_path, width=W, height=H, language_font_family=font_family)
                                    overlays.append((card_path, float(s), float(e)))
                                if overlays:
                                    _make_portrait_video_with_overlays(stock_video, concat_mp3, video_path, overlays, log_file=ffdbg)
                                else:
                                    # As last resort, output video without captions
                                    _make_portrait_video_with_audio(stock_video, concat_mp3, video_path, subtitles_path=None, drawtext_filter=None, log_file=ffdbg, subtitles_font=font_family)
                            except Exception:
                                # Last resort already attempted
                                pass

                # Thumbnail
                thumb = out_dir / 'thumbnail.jpg'
                if 'images_fallback' in locals() and images_fallback:
                    # Prefer the first generated slide image as the thumbnail for image-video fallback
                    try:
                        imgs_dir = dirs.get('images', out_dir / 'images')
                        first_slide = None
                        if imgs_dir and Path(imgs_dir).exists():
                            slides = sorted(Path(imgs_dir).glob('slide_*.png'))
                            first_slide = slides[0] if slides else None
                        if first_slide and first_slide.exists():
                            # Copy or convert to thumbnail.jpg
                            try:
                                from PIL import Image as _PILImage
                                im = _PILImage.open(first_slide).convert('RGB')
                                im.save(thumb, format='JPEG', quality=90)
                            except Exception:
                                # Fallback: ffmpeg convert
                                subprocess.run(['ffmpeg','-y','-i',str(first_slide), str(thumb)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass
                # If no thumbnail yet, extract from final video
                if not thumb.exists() or (thumb.exists() and thumb.stat().st_size < 1024):
                    _extract_thumbnail(video_path, thumb)
                # If still no good thumbnail, use a black placeholder
                if not thumb.exists() or thumb.stat().st_size < 1024:
                    try:
                        subprocess.run(['ffmpeg','-y','-f','lavfi','-i','color=color=black:size=720x1280:duration=1','-frames:v','1',str(thumb)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass

                # Persist post and publish SSE
                try:
                    if user_id is not None:
                        GENERATED_ROOT = _get_generated_root()
                        ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
                        IS_PRODUCTION = ENVIRONMENT == "production"
                        base_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip('/')

                        # Uploads (best effort)
                        video_https_url = ""
                        thumb_https_url = ""
                        try:
                            folder = f"lites_beauty_{safe}_{ts}"
                            obj_name = f"lites_beauty_{safe}_{ts}.mp4"
                            up = maybe_upload_and_url(
                                video_path,
                                parts=["content", "lites_beauty", folder, obj_name],
                                content_type="video/mp4",
                                make_public=True,
                            )
                            video_https_url = up.get("https_url", "")
                        except Exception as e:
                            logger.warning(f"[beauty] video upload skipped/failed: {e}")
                        try:
                            if thumb.exists():
                                thumb_obj_name = f"lites_beauty_{safe}_{ts}_thumbnail.jpg"
                                up_t = maybe_upload_and_url(
                                    thumb,
                                    parts=["content", "lites_beauty", folder, thumb_obj_name],
                                    content_type="image/jpeg",
                                    make_public=True,
                                )
                                thumb_https_url = up_t.get("https_url", "")
                                # Canonical thumbnail.jpg
                                try:
                                    up_t2 = maybe_upload_and_url(
                                        thumb,
                                        parts=["content", "lites_beauty", folder, "thumbnail.jpg"],
                                        content_type="image/jpeg",
                                        make_public=True,
                                    )
                                    thumb_https_url = up_t2.get("https_url", thumb_https_url)
                                except Exception:
                                    pass
                        except Exception as e:
                            logger.warning(f"[beauty] thumbnail upload skipped/failed: {e}")

                        # Local URLs
                        try:
                            rel_video = video_path.resolve().relative_to(GENERATED_ROOT).as_posix()
                        except Exception:
                            rel_video = video_path.as_posix()
                        local_video_url = f"{base_url}/videos/{rel_video}" if rel_video else ""
                        local_thumb_url = ""
                        try:
                            if thumb.exists():
                                rel_thumb = thumb.resolve().relative_to(GENERATED_ROOT).as_posix()
                                local_thumb_url = f"{base_url}/videos/{rel_thumb}"
                        except Exception:
                            pass

                        # Build images manifest (only meaningful for image-video fallback)
                        images_urls: list[str] = []
                        try:
                            if 'images_fallback' in locals() and images_fallback:
                                imgs_dir = dirs.get('images', out_dir / 'images')
                                if imgs_dir and Path(imgs_dir).exists():
                                    slides = sorted(Path(imgs_dir).glob('slide_*.png'))
                                    # Write images_manifest.json with relative paths under generated/
                                    rel_list: list[str] = []
                                    for s in slides:
                                        try:
                                            rel_s = s.resolve().relative_to(GENERATED_ROOT).as_posix()
                                        except Exception:
                                            rel_s = s.as_posix()
                                        rel_list.append(f"generated/{rel_s}")
                                    try:
                                        (out_dir / 'images_manifest.json').write_text(json.dumps({"images": rel_list}, ensure_ascii=False, indent=2), encoding='utf-8')
                                    except Exception:
                                        pass
                                    # For development, provide fully qualified local URLs for convenience
                                    if not IS_PRODUCTION:
                                        for s in slides:
                                            try:
                                                rel_s = s.resolve().relative_to(GENERATED_ROOT).as_posix()
                                                images_urls.append(f"{base_url}/videos/{rel_s}")
                                            except Exception:
                                                images_urls.append(f"{base_url}/videos/{s.as_posix()}")
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

                        # Stable content JSON (no slides images here)
                        tags = gem.get("tags") or []
                        content_json = _canonicalize_content(structured or [], narr or [], tags)

                        dbp = Session()
                        try:
                                                        # Ensure mlites tables exist
                            _ensure_mlites_tables(dbp)

                            # Get or create topic ID
                            topic_id = _get_or_create_mlites_topic_id(dbp, int(user_id), tp_title, item.get("minutes_per_day", 2))

                            # Derive sub-topic from first slide title if available (similar to mlites logic)
                            derived_sub_topic = None
                            try:
                                if isinstance(structured, list) and structured:
                                    t0 = (structured[0].get("title") or "").strip()
                                    if t0 and t0.lower() != "johnify":
                                        derived_sub_topic = t0[:255]
                            except Exception:
                                derived_sub_topic = None
                            try:
                                if derived_sub_topic and derived_sub_topic.strip().lower() == tp_title.strip().lower():
                                    derived_sub_topic = None
                            except Exception:
                                pass

                            # Get or create sub-topic ID if we have a derived sub-topic
                            sub_topic_id_val: Optional[int] = None
                            if topic_id is not None and derived_sub_topic:
                                sub_topic_id_val = _get_or_create_mlite_sub_topic_id(dbp, int(topic_id), derived_sub_topic)

                            # Build post topic with sub-topic if available
                            if derived_sub_topic and derived_sub_topic.strip():
                                ptopic_val = f"{tp_title} - {derived_sub_topic.strip()}"
                            else:
                                ptopic_val = tp_title

                            # Insert into user_posts with sub_topic_id if available
                            if sub_topic_id_val is not None:
                                dbp.execute(text(
                                    """
                                    INSERT INTO public.user_posts (user_id, post_path, post_topic, type, public, tags, sub_topic_id, created_on, content)
                                    VALUES (:uid, :ppath, :ptopic, 'mlites_beauty', TRUE, CAST(:tags AS JSONB), :stid, NOW(), :content)
                                    """
                                ), {
                                    "uid": int(user_id),
                                    "ppath": post_path,
                                    "ptopic": ptopic_val,
                                    "tags": json.dumps(tags or []),
                                    "stid": int(sub_topic_id_val),
                                    "content": json.dumps(content_json, ensure_ascii=False),
                                })
                            else:
                                dbp.execute(text(
                                    """
                                    INSERT INTO public.user_posts (user_id, post_path, post_topic, type, public, tags, created_on, content)
                                    VALUES (:uid, :ppath, :ptopic, 'mlites_beauty', TRUE, CAST(:tags AS JSONB), NOW(), :content)
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
                            logger.warning(f"[beauty] persist user_posts failed: {e}")
                        finally:
                            dbp.close()

                        # Publish SSE using the same event name as mlites for frontend compatibility
                        payload = {
                            "event": "mlite_video",
                            "topic": ptopic_val if 'ptopic_val' in locals() else tp_title,
                            "dir": f"generated/{out_dir.name}",
                            "post_path": post_path,
                            "video_url": video_url,
                            "thumbnail_url": thumbnail_url,
                            "images": images_urls,
                        }
                        # Thread-safe publish (works from background tasks)
                        try:
                            broker.publish_json_threadsafe(int(user_id), "mlite_video", payload)
                            logger.info(f"[beauty] SSE published: user_id={int(user_id)} event=mlite_video dir={payload.get('dir')} topic={payload.get('topic')}")
                        except Exception as pub_err:
                            logger.warning(f"[beauty] SSE publish failed for user_id={user_id}: {pub_err}")
                except Exception as e:
                    logger.warning(f"[beauty] post/publish block failed: {e}")
        except Exception as e:
            logger.exception(f"[beauty] background error: {e}")

    ts = int(time.time())
    jobs: List[Dict[str, str]] = []
    for item in topics:
        safe = _sanitize_filename(item["topic"])
        dir_rel = f"generated/mlites_beauty_{safe}_{ts}"
        jobs.append({"topic": item["topic"], "dir": dir_rel})

    bg.add_task(_run, topics, getattr(current_user, "user_email", None), getattr(current_user, "user_id", None), ts)
    return {"status": "started", "message": "Beauty MLite generation started.", "count": len(topics), "jobs": jobs}
