# Background opacity for Beauty image fallback (0.0 - 1.0)
try:
    _BEAUTY_BG_OPACITY = float(os.getenv("MLITES_BEAUTY_BG_OPACITY", "0.2") or "0.2")
except Exception:
    _BEAUTY_BG_OPACITY = 0.2
_BEAUTY_BG_OPACITY = max(0.0, min(1.0, _BEAUTY_BG_OPACITY))

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
import google.generativeai as genai
import os
import requests
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import os
import time
import json
import random
import subprocess
import logging
from PIL import Image, ImageDraw, ImageFont
import re
import requests
import asyncio
import time
from typing import List, Dict, Any, Optional, Tuple, Set

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

def _split_script_into_sections(narrations: List[str], max_sections: int = 3) -> List[Tuple[str, List[str]]]:
    if not narrations:
        return []
    n = len(narrations)
    section_size = max(1, n // max_sections)
    sections: List[Tuple[str, List[str]]] = []
    for i in range(0, n, section_size):
        section_narr = narrations[i:i + section_size]
        # Title from first narration, truncated
        first_narr = section_narr[0]
        title = first_narr[:50] + "..." if len(first_narr) > 50 else first_narr
        sections.append((title, section_narr))
    return sections

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


def _get_audio_duration(audio_path: Path) -> float:
    """Get duration of an audio file in seconds with fallback."""
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(audio_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10)
        duration_str = result.stdout.strip()
        if duration_str:
            duration = float(duration_str)
            # Validate duration is reasonable (between 0.1 and 300 seconds)
            if 0.1 <= duration <= 300:
                return duration
            else:
                try:
                    logger.warning(f"[beauty] Unreasonable audio duration {duration} for {audio_path}")
                except Exception:
                    pass
        return 2.5  # Default fallback
    except Exception as e:
        try:
            logger.error(f"[beauty] Failed to get audio duration: {e}")
        except Exception:
            pass
        return 2.5  # Default fallback


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


# Request throttling to prevent asyncio issues
_last_request_time = 0
_request_delay = 0.5  # 500ms between requests

def _throttled_request(url: str, headers: Optional[Dict] = None, params: Optional[Dict] = None, timeout: int = 10) -> Optional[requests.Response]:
    """Make a throttled HTTP request to prevent asyncio buffer issues."""
    global _last_request_time
    
    try:
        # Add delay between requests
        current_time = time.time()
        time_since_last = current_time - _last_request_time
        if time_since_last < _request_delay:
            time.sleep(_request_delay - time_since_last)
        
        _last_request_time = time.time()
        
        # Make request with proper session handling
        with requests.Session() as session:
            response = session.get(url, headers=headers, params=params, timeout=timeout)
            return response
            
    except Exception as e:
        try:
            logger.warning(f"[beauty] Request failed: {e}")
        except Exception:
            pass
        return None


def _generate_semantic_tags_polinations(narration_text: str, section_title: str) -> List[str]:
    """Generate semantic tags using Polinations text API as fallback."""
    try:
        prompt = f"""
        You are helping select stock videos for a video about "{section_title}". 
        The narration for this section is: "{narration_text}"
        
        Generate 5-8 specific, visual tags that would work well for finding stock videos on platforms like Pexels or Pixabay.
        
        IMPORTANT GUIDELINES:
        - Focus on ACTIONS, OBJECTS, and VISUAL ELEMENTS that can be filmed
        - Avoid abstract concepts, emotions, or ideas that can't be visualized
        - Be specific to the content (e.g., for "Tiramisu", use "dessert", "chocolate", "coffee", "sweet", "italian food")
        - For food topics: focus on cooking, ingredients, eating, restaurant scenes
        - For dance topics: focus on dancing, movement, performance, music, rhythm
        - For historical topics: focus on monuments, architecture, reenactments, historical scenes
        - For nature topics: focus on landscapes, wildlife, weather, natural elements
        
        Return only a comma-separated list of tags, no explanations.
        Examples: "dessert, chocolate, coffee, sweet, italian food, cooking"
        """
        
        response = requests.post(
            "https://text.pollinations.ai/openai/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": "Qwen3Guard-8B",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 100,
                "temperature": 0.7
            },
            timeout=5  # Reduced timeout
        )
        
        try:
            logger.info(f"[beauty] Polinations API response status: {response.status_code}")
        except Exception:
            pass
        
        if response.status_code == 200:
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content:
                tags = [tag.strip().lower() for tag in content.split(',')]
                # Filter out empty tags and limit to relevant ones
                return [tag for tag in tags if tag and len(tag) > 2][:8]
    except Exception as e:
        try:
            logger.warning(f"[beauty] Polinations tag generation failed: {e}")
        except Exception:
            pass
    
    # Simple rule-based fallback if all else fails
    fallback_tags = set()
    text = f"{section_title} {narration_text}".lower()
    
    # Only use basic visual keywords as final fallback - no hardcoded topics
    visual_keywords = {
        'nature', 'landscape', 'city', 'urban', 'people', 'person', 'woman', 'man',
        'technology', 'computer', 'phone', 'screen', 'ocean', 'mountain', 'forest',
        'sunset', 'sunrise', 'night', 'day', 'light', 'dark', 'color', 'bright',
        'happy', 'sad', 'excited', 'calm', 'peaceful', 'energetic', 'dramatic',
        'travel', 'adventure', 'home', 'office', 'work', 'business', 'education',
        'food', 'cooking', 'eating', 'health', 'fitness', 'exercise', 'sport',
        'music', 'art', 'creative', 'painting', 'drawing', 'dance', 'celebration',
        'family', 'friends', 'relationship', 'love', 'romance', 'wedding', 'party',
        'historical', 'ancient', 'monument', 'architecture', 'building', 'structure',
        'desert', 'sand', 'stone', 'marble', 'gold', 'silver', 'metal', 'wood',
        'royal', 'king', 'queen', 'palace', 'luxury', 'elegant', 'grand',
        'mystery', 'secret', 'hidden', 'dark', 'mysterious', 'unknown', 'puzzle',
        'power', 'strength', 'force', 'energy', 'movement', 'action', 'dynamic',
        'culture', 'tradition', 'ceremony', 'festival', 'celebration', 'ritual',
        'war', 'battle', 'revolution', 'freedom', 'independence', 'struggle',
        'science', 'research', 'discovery', 'innovation', 'technology', 'future',
        'religion', 'spiritual', 'temple', 'church', 'mosque', 'sacred', 'holy'
    }
    
    words = re.findall(r'\b\w+\b', text)
    for word in words:
        if word in visual_keywords:
            fallback_tags.add(word)
    
    return list(fallback_tags)[:8]


def _generate_semantic_tags(narration_text: str, section_title: str) -> List[str]:
    """Generate semantic tags based on the meaning and context of the narration."""
    # Try Gemini first, but fall back to keyword extraction immediately if it fails
    try:
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        # Try different model names that might be available
        models_to_try = [
            'gemini-3-flash-preview',
            'gemini-2.0-flash',
            'gemini-1.5-flash-latest', 
            'gemini-1.5-pro',
            'gemini-1.0-pro',
            'gemini-pro',
            'gemini-1.5-flash'
        ]
        
        for model_name in models_to_try:
            try:
                model = genai.GenerativeModel(model_name)
                try:
                    logger.info(f"[beauty] Trying Gemini model: {model_name}")
                    break
                except Exception:
                    pass
            except Exception as e:
                try:
                    logger.warning(f"[beauty] Gemini model {model_name} failed: {e}")
                except Exception:
                    pass
                continue
        
        if not model:
            raise Exception("No available Gemini model found")
        
        prompt = f"""
        You are helping select stock videos for a video about "{section_title}". 
        The narration for this section is: "{narration_text}"
        
        Generate 5-8 specific, visual tags that would work well for finding stock videos on platforms like Pexels or Pixabay.
        
        IMPORTANT GUIDELINES:
        - Focus on ACTIONS, OBJECTS, and VISUAL ELEMENTS that can be filmed
        - Avoid abstract concepts, emotions, or ideas that can't be visualized
        - Be specific to the content (e.g., for "Tiramisu", use "dessert", "chocolate", "coffee", "sweet", "italian food")
        - For food topics: focus on cooking, ingredients, eating, restaurant scenes
        - For dance topics: focus on dancing, movement, performance, music, rhythm
        - For historical topics: focus on monuments, architecture, reenactments, historical scenes
        - For nature topics: focus on landscapes, wildlife, weather, natural elements
        
        Return only a comma-separated list of tags, no explanations.
        Examples: "dessert, chocolate, coffee, sweet, italian food, cooking"
        """
        
        response = model.generate_content(prompt)
        if response.text:
            tags = [tag.strip().lower() for tag in response.text.split(',')]
            # Filter out empty tags and limit to relevant ones
            return [tag for tag in tags if tag and len(tag) > 2][:8]
    except Exception as e:
        try:
            logger.warning(f"[beauty] Semantic tag generation failed: {e}")
        except Exception:
            pass
    
    # Fallback to Polinations text API
    try:
        logger.info(f"[beauty] Falling back to Polinations API")
        return _generate_semantic_tags_polinations(narration_text, section_title)
    except Exception as e:
        try:
            logger.warning(f"[beauty] Polinations fallback failed: {e}")
        except Exception:
            pass
    
    # Enhanced keyword extraction with visual focus
    fallback_tags = set()
    text = f"{section_title} {narration_text}".lower()
    
    # Visual and conceptual keywords that work well for stock media
    visual_keywords = {
        'nature', 'landscape', 'city', 'urban', 'people', 'person', 'woman', 'man',
        'technology', 'computer', 'phone', 'screen', 'ocean', 'mountain', 'forest',
        'sunset', 'sunrise', 'night', 'day', 'light', 'dark', 'color', 'bright',
        'happy', 'sad', 'excited', 'calm', 'peaceful', 'energetic', 'dramatic',
        'travel', 'adventure', 'home', 'office', 'work', 'business', 'education',
        'food', 'cooking', 'eating', 'health', 'fitness', 'exercise', 'sport',
        'music', 'art', 'creative', 'painting', 'drawing', 'dance', 'celebration',
        'family', 'friends', 'relationship', 'love', 'romance', 'wedding', 'party',
        'historical', 'ancient', 'monument', 'architecture', 'building', 'structure',
        'desert', 'sand', 'stone', 'marble', 'gold', 'silver', 'metal', 'wood',
        'royal', 'king', 'queen', 'palace', 'luxury', 'elegant', 'grand',
        'mystery', 'secret', 'hidden', 'dark', 'mysterious', 'unknown', 'puzzle',
        'power', 'strength', 'force', 'energy', 'movement', 'action', 'dynamic',
        'culture', 'tradition', 'ceremony', 'festival', 'celebration', 'ritual',
        'war', 'battle', 'revolution', 'freedom', 'independence', 'struggle',
        'science', 'research', 'discovery', 'innovation', 'technology', 'future',
        'religion', 'spiritual', 'temple', 'church', 'mosque', 'sacred', 'holy'
    }
    
    words = re.findall(r'\b\w+\b', text)
    for word in words:
        if word in visual_keywords:
            fallback_tags.add(word)
    
    return list(fallback_tags)[:8]


def _pick_stock_video_from_pexels(query: str, preferred_gender: Optional[str] = None) -> Optional[str]:
    """Fetch stock video from Pexels API as backup."""
    try:
        api_key = os.getenv("PEXELS_API_KEY")
        if not api_key:
            return None
        
        headers = {"Authorization": api_key}
        params = {"query": query, "per_page": 1, "orientation": "portrait"}
        
        response = _throttled_request("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=10)
        if response and response.status_code == 200:
            data = response.json()
            videos = data.get("videos", [])
            if videos:
                video = videos[0]
                video_files = video.get("video_files", [])
                # Prefer hd quality
                hd_files = [vf for vf in video_files if vf.get("quality") == "hd"]
                if hd_files:
                    return hd_files[0]["link"]
                elif video_files:
                    return video_files[0]["link"]
        return None
    except Exception as e:
        try:
            logger.warning(f"[beauty] Pexels video search failed: {e}")
        except Exception:
            pass
        return None


def _pick_stock_video_from_pixabay(query: str, preferred_gender: Optional[str] = None) -> Optional[str]:
    """Fetch stock video from Pixabay API as backup."""
    try:
        api_key = os.getenv("PIXABAY_API_KEY")
        if not api_key:
            return None
        
        params = {
            "key": api_key,
            "q": query,
            "video_type": "film",
            "orientation": "vertical",
            "per_page": 5,
            "safesearch": "true"
        }
        
        response = _throttled_request("https://pixabay.com/api/videos/", params=params, timeout=10)
        if response and response.status_code == 200:
            data = response.json()
            videos = data.get("hits", [])
            if videos:
                # Get the best quality video
                video = videos[0]
                videos_dict = video.get("videos", {})
                
                # Try different sizes in order of preference
                for size in ["large", "medium", "small", "tiny"]:
                    if size in videos_dict:
                        return videos_dict[size]["url"]
        return None
    except Exception as e:
        try:
            logger.warning(f"[beauty] Pixabay video search failed: {e}")
        except Exception:
            pass
        return None


def _pick_stock_image_from_pexels(query: str, preferred_gender: Optional[str] = None) -> Optional[str]:
    """Fetch stock image from Pexels as fallback when no videos are found."""
    try:
        api_key = os.getenv("PEXELS_API_KEY")
        if not api_key:
            return None
        
        headers = {"Authorization": api_key}
        params = {"query": query, "per_page": 1, "orientation": "portrait"}
        
        response = _throttled_request("https://api.pexels.com/v1/search", headers=headers, params=params, timeout=10)
        if response and response.status_code == 200:
            data = response.json()
            photos = data.get("photos", [])
            if photos:
                photo = photos[0]
                # Get the best size for portrait video
                for size in ["large", "medium", "small"]:
                    if size in photo.get("src", {}):
                        return photo["src"][size]
        return None
    except Exception as e:
        try:
            logger.warning(f"[beauty] Pexels image search failed: {e}")
        except Exception:
            pass
        return None


def _pick_stock_image_from_pixabay(query: str, preferred_gender: Optional[str] = None) -> Optional[str]:
    """Fetch stock image from Pixabay as fallback."""
    try:
        api_key = os.getenv("PIXABAY_API_KEY")
        if not api_key:
            return None
        
        params = {
            "key": api_key,
            "q": query,
            "image_type": "photo",
            "orientation": "vertical",
            "per_page": 5,
            "safesearch": "true",
            "min_width": 720,
            "min_height": 1280
        }
        
        response = _throttled_request("https://pixabay.com/api/", params=params, timeout=10)
        if response and response.status_code == 200:
            data = response.json()
            images = data.get("hits", [])
            if images:
                # Get the best quality image
                image = images[0]
                return image.get("webformatURL") or image.get("largeImageURL")
        return None
    except Exception as e:
        try:
            logger.warning(f"[beauty] Pixabay image search failed: {e}")
        except Exception:
            pass
        return None




def _enhanced_semantic_stock_selection(section_title: str, narration_text: str, preferred_gender: Optional[str] = None) -> Tuple[Optional[str], bool]:
    """
    Enhanced semantic stock selection with multiple fallback strategies.
    Returns: (stock_url, is_image_fallback)
    """
    # Generate semantic tags
    semantic_tags = _generate_semantic_tags(narration_text, section_title)
    
    # Create dynamic search queries from semantic tags
    search_queries = []
    
    # Add main topic first
    filler_words_basic = ['the', 'but', 'and', 'for', 'with', 'were', 'this', 'that', 'from', 'they', 'have', 'been', 'are', 'was', 'be', 'to', 'of', 'in', 'it', 'you', 'he', 'she', 'we', 'them', 'his', 'her', 'its', 'our', 'their', 'who', 'which', 'who', 'what', 'where', 'when', 'why', 'how', 'that', 'this', 'these', 'those', 'am', 'is', 'was', 'were', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'a', 'an', 'at', 'by', 'from', 'in', 'into', 'of', 'on', 'onto', 'out', 'over', 'through', 'to', 'up', 'with', 'about', 'against', 'between', 'among', 'during', 'before', 'after', 'above', 'below', 'under', 'again', 'further', 'then', 'once', 'imagine', 'one', 'peaceful', 'movement', 'temple', 'sacred']
    
    main_topic = section_title.split()[0] if section_title else ""
    if main_topic and len(main_topic) > 2 and main_topic.lower() not in filler_words_basic:
        search_queries.append(main_topic)
    
    # Add semantic tags (prioritize meaningful ones)
    filler_words = {
        'the', 'but', 'and', 'for', 'with', 'were', 'this', 'that', 'from', 'they', 'have', 'been', 'not', 'all', 'can', 'will', 'just', 'so', 'if', 'out', 'up', 'what', 'when', 'where', 'how', 'than', 'then', 'some', 'more', 'very', 'also', 'even', 'only', 'own', 'same', 'such', 'too', 'think', 'say', 'well', 'get', 'go', 'know', 'take', 'come', 'see', 'look', 'want', 'give', 'use', 'find', 'tell', 'ask', 'work', 'seem', 'feel', 'try', 'leave', 'call',
        # Additional common filler words
        'are', 'was', 'were', 'be', 'to', 'of', 'in', 'it', 'you', 'he', 'she', 'we', 'them', 'his', 'her', 'its', 'our', 'their', 'who', 'whom', 'which', 'who', 'whom', 'whose', 'what', 'where', 'when', 'why', 'how', 'that', 'this', 'these', 'those', 'am', 'is', 'was', 'were', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'done', 'shall', 'should', 'could', 'would', 'might', 'must', 'may', 'can', 'will', 'would', 'should', 'could', 'might', 'must',
        # Articles and prepositions
        'a', 'an', 'the', 'at', 'by', 'for', 'from', 'in', 'into', 'of', 'on', 'onto', 'out', 'over', 'through', 'to', 'up', 'with', 'about', 'against', 'between', 'among', 'during', 'before', 'after', 'above', 'below', 'under', 'again', 'further', 'then', 'once',
        # Abstract/conceptual words that don't work well for stock media
        'imagine', 'one', 'peaceful', 'movement', 'temple', 'sacred', 'struggle', 'dignity', 'freedom', 'independence', 'revolution', 'concept', 'idea', 'theory', 'philosophy', 'belief', 'principle', 'value', 'ideal', 'dream', 'hope', 'faith', 'trust', 'courage', 'wisdom', 'knowledge', 'understanding', 'awareness', 'consciousness'
    }
    meaningful_tags = [tag for tag in semantic_tags if len(tag) > 2 and tag.lower() not in filler_words]
    search_queries.extend(meaningful_tags[:6])
    
    # Remove duplicates and empty queries
    search_queries = [q for q in list(dict.fromkeys(search_queries)) if q and len(q.strip()) > 2]
    
    try:
        logger.info(f"[beauty] Generated semantic tags: {semantic_tags}")
        logger.info(f"[beauty] Search queries: {search_queries}")
    except Exception:
        pass
    
    # Strategy 1: Try Pexels videos with specific queries only
    for query in search_queries[:4]:  # Try top 4 most specific queries
        video_url = _pick_stock_video_from_pexels(query, preferred_gender)
        if video_url:
            try:
                logger.info(f"[beauty] Found Pexels video for query: {query}")
            except Exception:
                pass
            return video_url, False
    
    # Strategy 2: Try Pixabay videos with specific queries
    for query in search_queries[:4]:
        video_url = _pick_stock_video_from_pixabay(query, preferred_gender)
        if video_url:
            try:
                logger.info(f"[beauty] Found Pixabay video for query: {query}")
            except Exception:
                pass
            return video_url, False
    
    # Strategy 3: Try Pexels images as fallback (more specific queries)
    for query in search_queries[:3]:
        image_url = _pick_stock_image_from_pexels(query, preferred_gender)
        if image_url:
            try:
                logger.info(f"[beauty] Using Pexels image fallback for query: {query}")
            except Exception:
                pass
            return image_url, True
    
    # Strategy 4: Try Pixabay images as final fallback
    for query in search_queries[:3]:
        image_url = _pick_stock_image_from_pixabay(query, preferred_gender)
        if image_url:
            try:
                logger.info(f"[beauty] Using Pixabay image fallback for query: {query}")
            except Exception:
                pass
            return image_url, True
    
    # Strategy 5: Fall back to database methods
    try:
        logger.info(f"[beauty] All APIs failed, falling back to database")
    except Exception:
        pass
    
    # Try existing database methods as last resort
    try:
        from .mlites import _pick_stock_video_by_tags, _pick_stock_video_by_gender
    except ImportError:
        try:
            logger.warning(f"[beauty] Could not import database methods, using random fallback")
        except Exception:
            pass
        return None, False
    
    # Extract topic words from title and narration
    topic_words = section_title.split() + narration_text.split()[:10]
    topic_words = [w for w in topic_words if len(w) > 3][:5]
    
    # Try simple tag-based selection
    stock_video = _pick_stock_video_by_tags(topic_words, preferred_gender)
    if stock_video:
        return stock_video, False
    
    stock_video = _pick_stock_video_by_tags([section_title], preferred_gender)
    if stock_video:
        return stock_video, False
    
    stock_video = _pick_stock_video_by_gender(preferred_gender)
    if stock_video:
        return stock_video, False
    
    return None, False


def _make_portrait_video_with_audio(stock_video: Path | str, audio_mp3: Path, out_mp4: Path, *, subtitles_path: Optional[Path] = None, drawtext_filter: Optional[str] = None, log_file: Optional[Path] = None, subtitles_font: str = "Arial", strict: bool = False, is_image_fallback: bool = False) -> Path:
    # Scale/pad to portrait; loop video if shorter than audio; cut to shortest
    env = _ffmpeg_env_settings()
    W, H = env["width"], env["height"]
    vf = f"fps=30,scale={W}:{H}:flags=fast_bilinear:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    # Build subtitles filter if provided
    sub_filter = None
    if subtitles_path is not None and subtitles_path.exists():
        try:
            logger.info(f"[beauty] Burning subtitles from: {subtitles_path}")
        except Exception:
            pass
        # Properly escape Windows paths for ffmpeg subtitles filter (escape \\ and :) and quotes
        sp = _esc_path(str(subtitles_path))
        # Style: bottom-centered, boxed look via libass outline
        force_style = (
            f"FontName={subtitles_font},FontSize=6,Bold=1,OutlineColour=&H80000000&,BorderStyle=3,Outline=2,Shadow=0,Alignment=2,MarginV=20"
        )
        sub_filter = f"subtitles='{sp}':force_style='{force_style}'"
    else:
        try:
            logger.warning(f"[beauty] No subtitles path provided or file doesn't exist: {subtitles_path}")
        except Exception:
            pass

    is_url = isinstance(stock_video, str) and stock_video.lower().startswith(("http://","https://"))
    
    # Handle image fallback - convert image to video
    if is_image_fallback:
        try:
            # Download and convert image to video
            idx = out_mp4.stem.split("_")[1] if "_" in out_mp4.stem else "0"
            image_path = out_mp4.parent / f'fallback_image_{idx}.jpg'
            
            if is_url:
                # Download image with throttled request
                response = _throttled_request(stock_video, timeout=10)
                if response and response.status_code == 200:
                    with open(image_path, 'wb') as f:
                        f.write(response.content)
            else:
                # Copy local image
                import shutil
                shutil.copy2(stock_video, image_path)
            
            # Create video from image with slow zoom/pan effect
            vf_image = f"fps=30,scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1"
            vf_image += ",zoompan=z='if(lte(on,1),1+0.001*on,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1"
            
            cmd = [
                "ffmpeg","-y",
                "-loop","1","-i", str(image_path),
                "-i",str(audio_mp3),
                "-shortest",
                "-map","0:v:0","-map","1:a:0",
                "-c:v","libx264","-preset",str(env["preset"]),"-crf",str(env["crf"]),"-r","30",
                "-vf", vf_image,
                "-aspect","9:16",
                "-pix_fmt","yuv420p",
                "-c:a","aac","-b:a","128k",
                str(out_mp4)
            ]
            
            if log_file:
                with open(log_file, 'ab') as lf:
                    lf.write(('\n\n=== ffmpeg (image fallback) ===\n' + ' '.join(cmd) + '\n').encode('utf-8', errors='ignore'))
                    subprocess.run(cmd, check=True, stdout=lf, stderr=lf)
            else:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Cleanup
            try:
                image_path.unlink(missing_ok=True)
            except Exception:
                pass
            
            return out_mp4
            
        except Exception as e:
            try:
                logger.warning(f"[beauty] Image fallback failed: {e}")
            except Exception:
                pass
            # Fall back to original video logic
            pass
    
    # If remote URL, re-encode to a local mezzanine file so we can loop it reliably (handles non-seekable/chunked sources)
    local_src: Path | str = stock_video
    if is_url:
        try:
            idx = out_mp4.stem.split("_")[1]  # extract idx from segment_{idx}.mp4
            local_src = out_mp4.parent / f'stock_src_{idx}.mp4'
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
        # Use -t to limit to audio duration instead of -shortest to avoid cutting audio early
        "-t", str(_get_audio_duration(audio_mp3)),
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
                    # Use -t to limit to audio duration instead of -shortest
                    "-t", str(_get_audio_duration(audio_mp3)),
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
            limit = 100
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
        ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
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

                # Check for identical narrations and fix
                if len(narr) > 1 and len(set(narr)) <= 1:
                    try:
                        logger.warning(f"[beauty] All {len(narr)} narrations are identical, numbering them to prevent repeated captions")
                        base = narr[0] if narr else "Default narration."
                        narr = [f"Part {i+1}: {base}" for i in range(len(narr))]
                    except Exception as e:
                        logger.error(f"[beauty] Failed to fix identical narrations: {e}")

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
                    # Build subtitles (SRT) for list_mode
                    captions_path = out_dir / 'captions.srt'
                    cues: List[tuple[float, float, str]] = []
                    t = 0.0
                    for idx, p in enumerate(mp3_files):
                        dur_meas = float(_get_audio_duration(Path(p)))
                        # Use actual measured duration, but ensure reasonable bounds
                        if dur_meas and dur_meas > 0:
                            duration = dur_meas
                        else:
                            duration = 2.5  # Fallback duration
                        text_line = str(narr[idx]) if idx < len(narr) else ""
                        start, end = t, t + duration
                        cues.append((start, end, text_line))
                        t = end
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
                    # Expose cues
                    try:
                        use_cues = list(cues)
                    except Exception:
                        use_cues = []
                    video_path = out_dir / f"mlites_beauty_{safe}_{ts}.mp4"
                else:
                    # Split into sections for multiple stock videos
                    try:
                        tags = gem.get("tags") or []
                    except Exception:
                        tags = []
                    topic_tags = _normalize_tags(tags)
                    preferred_gender = (os.getenv("MLITES_BEAUTY_DEFAULT_GENDER", "") or "").strip().lower() or None
                    sections = _split_script_into_sections(narr, max_sections=3)
                    # Concatenate all narration audio into one for multi-section fallback
                    concat_mp3 = out_dir / 'narration_full.mp3'
                    list_file = out_dir / 'inputs_copy.txt'
                    with list_file.open('w', encoding='utf-8') as f:
                        for p in mp3_files:
                            f.write(f"file '{p.as_posix()}'\n")
                    subprocess.run([
                        'ffmpeg','-y','-f','concat','-safe','0','-i',str(list_file),'-c','copy', str(concat_mp3)
                    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    section_mp3_groups = []
                    start = 0
                    for _, section_narr in sections:
                        count = len(section_narr)
                        section_mp3_groups.append(mp3_files[start:start+count])
                        start += count
                    video_segments = []
                    def _fmt(ts: float) -> str:
                        total_ms = max(0, int(round(ts * 1000)))
                        hh = total_ms // 3600000
                        mm = (total_ms % 3600000) // 60000
                        ss = (total_ms % 60000) // 1000
                        ms = total_ms % 1000
                        return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"
                    for idx, (section_title, section_narr) in enumerate(sections):
                        section_mp3s = section_mp3_groups[idx]
                        if len(section_mp3s) == 1:
                            section_audio = section_mp3s[0]
                        else:
                            section_audio = out_dir / f"section_audio_{idx}.mp3"
                            try:
                                _concat_mp3s(section_mp3s, section_audio)
                            except Exception:
                                list_file = out_dir / f"inputs_reencode_{idx}.txt"
                                with list_file.open('w', encoding='utf-8') as f:
                                    for p in section_mp3s:
                                        f.write(f"file '{p.as_posix()}'\n")
                                subprocess.run([
                                    'ffmpeg','-y','-f','concat','-safe','0','-i',str(list_file),'-c:a','libmp3lame','-b:a','128k',str(section_audio)
                                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        # Pick stock using enhanced semantic selection
                        # Combine all narration text for better semantic understanding
                        full_narration = " ".join(section_narr)
                        stock_url, is_image_fallback = _enhanced_semantic_stock_selection(section_title, full_narration, preferred_gender)
                        
                        if not stock_url:
                            try:
                                logger.warning(f"[beauty] No stock media found for section {idx}")
                            except Exception:
                                pass
                            continue
                            
                        try:
                            logger.info(f"[beauty] Section {idx}: Using {'image' if is_image_fallback else 'video'} fallback: {stock_url}")
                        except Exception:
                            pass
                        
                        # Skip per-segment subtitle burning in multi-section mode; captions will be burned after concatenation
                        out_mp4 = out_dir / f"segment_{idx}.mp4"
                        # Temporarily suppress subtitle burn warnings for multi-section segments
                        import logging as _logging
                        _logging.getLogger("mlites_beauty").setLevel(_logging.ERROR)
                        try:
                            success = _make_portrait_video_with_audio(stock_url, str(section_audio), out_mp4, subtitles_path=None, drawtext_filter=None, is_image_fallback=is_image_fallback)
                        finally:
                            # Restore normal logging level
                            _logging.getLogger("mlites_beauty").setLevel(_logging.INFO)
                        if success:
                            video_segments.append(out_mp4)
                        else:
                            try:
                                logger.warning(f"[beauty] Failed to create segment {idx}")
                            except Exception:
                                pass
                    if len(video_segments) == 1:
                        final_video = video_segments[0]
                    else:
                        concat_file = out_dir / "concat_list.txt"
                        with concat_file.open("w") as f:
                            for seg in video_segments:
                                f.write(f"file '{seg.name}'\n")
                        final_video = out_dir / f"mlites_beauty_{safe}_{ts}.mp4"
                        subprocess.run([
                            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(final_video)
                        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(out_dir))
                    video_path = final_video
                    multi_stock = True
                    images_fallback = False
                    stock_video = None

                    # After concatenation, burn captions into the final video
                    try:
                        # Create a single SRT for the entire video by merging section captions
                        final_srt = out_dir / 'final_captions.srt'
                        cues_all: List[tuple[float, float, str]] = []
                        t_offset = 0.0
                        for idx, (_, section_narr) in enumerate(sections):
                            section_mp3s = section_mp3_groups[idx]
                            for i, p in enumerate(section_mp3s):
                                dur_meas = float(_get_audio_duration(Path(p)))
                                # Use actual measured duration, but ensure reasonable bounds
                                if dur_meas and dur_meas > 0:
                                    duration = dur_meas
                                else:
                                    duration = 2.5  # Fallback duration
                                text_line = section_narr[i] if i < len(section_narr) else ""
                                cues_all.append((t_offset, t_offset + duration, text_line))
                                t_offset += duration
                        def _fmt(ts: float) -> str:
                            total_ms = max(0, int(round(ts * 1000)))
                            hh = total_ms // 3600000
                            mm = (total_ms % 3600000) // 60000
                            ss = (total_ms % 60000) // 1000
                            ms = total_ms % 1000
                            return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"
                        with final_srt.open('w', encoding='utf-8') as f:
                            for i, (s, e, txt) in enumerate(cues_all, 1):
                                f.write(f"{i}\n{_fmt(s)} --> {_fmt(e)}\n{txt}\n\n")
                        # Burn captions into final video
                        env = _ffmpeg_env_settings()
                        tmp_burn = out_dir / 'final_with_captions.mp4'
                        
                        try:
                            logger.info(f"[beauty] Final video exists: {final_video.exists()}")
                            logger.info(f"[beauty] Final SRT exists: {final_srt.exists()}")
                            if final_srt.exists():
                                srt_content = final_srt.read_text(encoding='utf-8', errors='ignore')[:500]
                                logger.info(f"[beauty] SRT content preview: {srt_content}")
                        except Exception:
                            pass
                        
                        # Burn captions into final video using simple subtitle file approach
                        env = _ffmpeg_env_settings()
                        tmp_burn = out_dir / 'final_with_captions.mp4'
                        
                        try:
                            logger.info(f"[beauty] Final video exists: {final_video.exists()}")
                            logger.info(f"[beauty] Final SRT exists: {final_srt.exists()}")
                            if final_srt.exists():
                                srt_content = final_srt.read_text(encoding='utf-8', errors='ignore')[:500]
                                logger.info(f"[beauty] SRT content preview: {srt_content}")
                        except Exception:
                            pass
                        
                        # Simple approach: use FFmpeg's subtitles filter with the SRT file directly
                        try:
                            # Use FFmpeg subtitles filter - much more reliable than custom drawtext
                            # Use relative path to avoid Windows path parsing issues
                            srt_relative = final_srt.relative_to(out_dir)
                            cmd = [
                                'ffmpeg', '-y',
                                '-i', str(final_video),
                                '-vf', f"subtitles='{srt_relative}':force_style='FontName=Arial,FontSize=6,Bold=0,BackColour=&H80000000&,BorderStyle=4,Outline=0,Shadow=0,Alignment=2,MarginV=10'",
                                '-c:v', 'libx264', '-preset', str(env['preset']), '-crf', str(env['crf']), '-r', '30',
                                '-c:a', 'copy',
                                str(tmp_burn)
                            ]
                            
                            logger.info(f"[beauty] Using FFmpeg subtitles filter with relative SRT path: {srt_relative}")
                            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(out_dir))
                            
                            if result.returncode == 0:
                                logger.info(f"[beauty] FFmpeg subtitles successful: {tmp_burn.exists()}")
                            else:
                                logger.warning(f"[beauty] FFmpeg subtitles failed: {result.stderr}")
                                raise Exception("FFmpeg subtitles failed")
                                
                        except Exception as e:
                            logger.warning(f"[beauty] Subtitle burning failed: {e}")
                            # Fallback: simple hardcoded text
                            cmd = [
                                'ffmpeg', '-y',
                                '-i', str(final_video),
                                '-vf', "drawtext=text='Captions Available':fontsize=24:fontcolor=white:x=(w-text_w)/2:y=h-50:box=1:boxcolor=black@0.5:boxborderw=5",
                                '-c:v', 'libx264', '-preset', str(env['preset']), '-crf', str(env['crf']), '-r', '30',
                                '-c:a', 'copy',
                                str(tmp_burn)
                            ]
                            logger.info("[beauty] Using fallback drawtext")
                            subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                        # Replace final video
                        final_video.unlink(missing_ok=True)
                        tmp_burn.rename(final_video)
                        video_path = final_video
                    except Exception as e:
                        try:
                            logger.warning(f"[beauty] Failed to burn captions into final video: {e}")
                        except Exception:
                            pass

                # Skip redundant single-stock fallback; multi-section already handled
                
                # Persist the effective ffmpeg command used for debugging
                try:
                    ffdbg = out_dir / 'ffmpeg_cmd.txt'
                    ffdbg.write_text('drawtext_filter=' + (drawtext_filter or ''), encoding='utf-8')
                except Exception:
                    ffdbg = None

                font_family = 'Arial'

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
                                                '-vf', f"subtitles='{sp}':force_style='FontName=Arial,FontSize=6,Bold=1,OutlineColour=&H80000000&,BorderStyle=3,Outline=2,Shadow=0,Alignment=2,MarginV=20'",
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
                    if 'multi_stock' in locals() and multi_stock:
                        pass
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
                            # Fallback to subtitles/drawtext path only if stock_video is valid
                            if stock_video:
                                _make_portrait_video_with_audio(
                                    stock_video, concat_mp3, video_path,
                                    subtitles_path=captions_path if captions_path.exists() else None,
                                    drawtext_filter=drawtext_filter,
                                    log_file=ffdbg,
                                    subtitles_font=font_family
                                )
                    else:
                        # Production default: single-pass drawtext (lower memory than multi-input overlays)
                        # Only run if stock_video is valid (not None)
                        if stock_video:
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
