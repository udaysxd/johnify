from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from pathlib import Path
import time
import os
import json
import subprocess
from PIL import Image, ImageDraw, ImageFont
import google.generativeai as genai
import logging
from sqlalchemy import text
from .database import Session

# Independent Lites router (no imports from learn or tutor)
router = APIRouter(prefix="/api/lites", tags=["lites"])  

# Module logger
logger = logging.getLogger("lites")
if not logger.handlers:
    handler = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] lites: %(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Configurable sub-topics table name (existing in DB)
# Default updated to new table name: public.lites_sub_topics
SUB_TOPICS_TABLE = os.getenv("LITES_SUB_TOPICS_TABLE", "public.lites_sub_topics")

# SSE broker (per-user streams)
try:
    from .services.sse_broker import broker
except Exception:
    # fallback relative import if structure differs
    from .services.sse_broker import broker  # type: ignore

# ---- Local helpers (kept private to lites) ----

def _sanitize_filename(filename: str) -> str:
    import re, unicodedata
    filename = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
    filename = re.sub(r'[\\/*?:"<>| ]', '_', filename)
    filename = re.sub(r'_+', '_', filename).strip('_')
    return filename or "lite"

def _ensure_dirs(base: Path) -> Dict[str, Path]:
    base.mkdir(parents=True, exist_ok=True)
    (base / "images").mkdir(exist_ok=True)
    (base / "audio").mkdir(exist_ok=True)
    return {"images": base / "images", "audio": base / "audio"}

def _find_font(candidates: List[str], size: int):
    for fp in candidates:
        try:
            if os.path.exists(fp):
                return ImageFont.truetype(fp, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None

def _create_title_image(text: str, out_path: Path, width: int = 1280, height: int = 720) -> None:
    img = Image.new('RGB', (width, height), color=(26, 28, 34))
    draw = ImageDraw.Draw(img)
    # Font candidates across platforms
    font_large = _find_font([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        r"C:\\Windows\\Fonts\\segoeuib.ttf",
        r"C:\\Windows\\Fonts\\arialbd.ttf",
    ], 72)
    font_small = _find_font([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        r"C:\\Windows\\Fonts\\segoeui.ttf",
        r"C:\\Windows\\Fonts\\arial.ttf",
    ], 28)

    # Wrap text roughly
    words = (text or "Lites").strip()[:160].split()
    lines: List[str] = []
    current = ""
    def text_w(s: str, f):
        try:
            bbox = draw.textbbox((0,0), s, font=f)
            return bbox[2] - bbox[0]
        except Exception:
            try:
                return int(draw.textlength(s, font=f))  # type: ignore[attr-defined]
            except Exception:
                return len(s) * 14
    max_w = width - 320
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
            bbox = draw.textbbox((0,0), ln, font=font_large)
            w = bbox[2]-bbox[0]; h=bbox[3]-bbox[1]
        except Exception:
            w = text_w(ln, font_large); h = 72
        total_h += h + 10
        line_sizes.append((w,h))
    total_h -= 10 if lines else 0
    y = (height - total_h)//2
    for i, ln in enumerate(lines):
        w, h = line_sizes[i]
        x = (width - w)//2
        # subtle shadow
        draw.text((x+3, y+3), ln, fill=(0,0,0), font=font_large)
        draw.text((x, y), ln, fill=(240,240,240), font=font_large)
        y += h + 10

    # small brand note
    brand = "johnify lites"
    try:
        bw = text_w(brand, font_small)
    except Exception:
        bw = len(brand) * 10
    bx = width - bw - 24
    by = height - 24 - 28
    draw.text((bx+2, by+2), brand, fill=(0,0,0), font=font_small)
    draw.text((bx, by), brand, fill=(200,200,200), font=font_small)

    img.save(out_path)


def _create_silent_video_from_image(image_path: Path, out_path: Path, duration: float = 8.0) -> None:
    # Build a silent mp4 showing the image scaled to 1280x720
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-loop", "1", "-t", str(max(1.0, duration)), "-i", str(image_path),
        "-f", "lavfi", "-t", str(max(1.0, duration)), "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-vf", "fps=30,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-c:a", "aac", "-shortest",
        str(out_path)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


""" Lites-only slide generation and narration via Gemini """
def _gemini_generate(topic: str) -> Dict[str, Any]:
    """Call Gemini to produce slide content, narrations, and tags.
    Returns dict: { slides: [{title, bullets: [..]}], narrations: [..], tags: [..] }
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set for Gemini")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("models/gemini-2.5-flash-lite")
    prompt = (
        "You are generating concise educational slide content for the topic.\n"
        "Return ONLY a strict JSON object with keys: slides, narrations, tags.\n"
        "- slides: array of 5 objects: {title: string, bullets: array of 4-6 concise bullet strings}\n"
        "- narrations: array of 5 strings, one per slide; 2 sentences each, friendly and clear.\n"
        "- tags: array of 5-10 short keywords (lowercase, no punctuation).\n"
        f"Topic: {topic}\n"
    )
    resp = model.generate_content(prompt)
    text = ""
    try:
        text = resp.text or ""
    except Exception:
        text = str(resp)

    # Try to extract JSON
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

    # Basic validation and fallback
    slides = data.get("slides") or []
    narr = data.get("narrations") or []
    tags = data.get("tags") or []
    if not isinstance(slides, list) or len(slides) == 0:
        slides = [
            {"title": topic.strip().title() or "Overview", "bullets": [
                "What it is", "Why it matters", "Where it's used", "First steps"
            ]},
            {"title": "Core Ideas", "bullets": ["Idea 1", "Idea 2", "Idea 3", "Idea 4"]},
            {"title": "How To Learn", "bullets": ["Step 1", "Step 2", "Step 3", "Step 4"]},
            {"title": "Examples", "bullets": ["Example 1", "Example 2", "Example 3", "Example 4"]},
            {"title": "Summary", "bullets": ["Takeaway 1", "Takeaway 2", "Next steps", "Resources"]},
        ]
    if not isinstance(narr, list) or len(narr) < len(slides):
        narr = [
            f"This slide covers {s.get('title','the topic')}. Focus on the key points." for s in slides
        ]
    if not isinstance(tags, list) or len(tags) == 0:
        tags = [topic.split(" ")[0].lower(), "basics", "overview"]
    return {"slides": slides, "narrations": narr, "tags": tags}


""" Lites-only TTS (replicated logic) """
def _fresh_dir(path: str) -> Path:
    p = Path(path)
    if p.exists():
        import shutil
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)
    return p

def _narrations_to_mp3(narrations: List[str], out_dir: str) -> Path:
    from google.cloud import texttospeech
    out_p = _fresh_dir(out_dir)
    client = texttospeech.TextToSpeechClient()
    voice = texttospeech.VoiceSelectionParams(
        language_code="en-GB",
        name="en-GB-Neural2-D",
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.0,
        pitch=0.0,
        sample_rate_hertz=44100,
    )
    for i, narration in enumerate(narrations):
        synthesis_input = texttospeech.SynthesisInput(text=narration)
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        mp3_path = out_p / f"s{i+1:03d}.mp3"
        mp3_path.write_bytes(response.audio_content)
        logger.info(f"Created {mp3_path}")
    return out_p


""" Lites-only video stitching (replicated logic) """
def _get_audio_duration(mp3: Path) -> float:
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', str(mp3)],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout or '{}')
        return float(data.get('format', {}).get('duration', 0.0))
    except Exception as e:
        logger.warning(f"duration error: {e}")
        return 0.0

def _create_slide_video(img: Path, mp3: Path, out_mp4: Path, duration_override: Optional[float] = None):
    try:
        duration = max(0.1, float(duration_override) if duration_override is not None else float(_get_audio_duration(mp3)))
        subprocess.run([
            'ffmpeg','-y','-loop','1','-i',str(img),'-i',str(mp3),'-t',str(duration),
            '-c:v','libx264','-preset','ultrafast','-tune','stillimage','-crf','28','-r','30','-threads','1','-pix_fmt','yuv420p',
            '-c:a','aac','-ar','44100','-ac','2','-b:a','128k','-shortest', str(out_mp4)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return out_mp4
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
            # create silent fallback
            silent = temp_dir / 'silent.mp3'
            subprocess.run(['ffmpeg','-y','-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100','-t','5','-c:a','libmp3lame',str(silent)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            mp3s = [silent] * len(imgs)
        pair_n = min(len(imgs), len(mp3s))
        # Duration budgeting: keep total under 90s with 1s safety margin
        max_total = 89.0
        min_per = 2.0
        # avoid division by zero already ensured by pair_n>0
        per_cap = max(min_per, max_total / float(pair_n))
        # Also cap extreme long per-slide durations
        per_cap = min(per_cap, 20.0)
        segs = []
        for i in range(pair_n):
            seg = temp_dir / f"seg_{i+1:03d}.mp4"
            orig = _get_audio_duration(mp3s[i])
            use_dur = min(per_cap, max(min_per, orig))
            _create_slide_video(imgs[i], mp3s[i], seg, duration_override=use_dur)
            segs.append(seg)
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
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"Final video: {out_mp4}")
        return out_mp4
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
def _draw_text_slide(
    title: str,
    content: str,
    out_path: Path,
    width: int = 1280,
    height: int = 720,
    mode: str = "full",
    text_color=(0, 0, 0),
):
    img = Image.new('RGB', (width, height), color=(245, 246, 250))
    draw = ImageDraw.Draw(img)
    title_font = _find_font([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        r"C:\\Windows\\Fonts\\segoeuib.ttf",
        r"C:\\Windows\\Fonts\\arialbd.ttf",
    ], 48)
    body_font = _find_font([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        r"C:\\Windows\\Fonts\\segoeui.ttf",
        r"C:\\Windows\\Fonts\\arial.ttf",
    ], 28)

    # Special branding end-card: center the title and skip body
    if mode == "brand":
        try:
            tb = draw.textbbox((0, 0), title, font=title_font)
            tw, th = tb[2]-tb[0], tb[3]-tb[1]
        except Exception:
            tw = len(title) * 14; th = 48
        tx = (width - tw) // 2
        ty = (height - th) // 2
        draw.text((tx+2, ty+2), title, fill=(0,0,0), font=title_font)
        draw.text((tx, ty), title, fill=(20,20,20), font=title_font)
        img.save(out_path)
        return

    pad = 40
    # Title (normal slide)
    try:
        tb = draw.textbbox((0, 0), title, font=title_font)
        tw, th = tb[2]-tb[0], tb[3]-tb[1]
    except Exception:
        tw = len(title) * 14; th = 48
    tx = pad
    ty = pad
    draw.text((tx+2, ty+2), title, fill=(0,0,0), font=title_font)
    draw.text((tx, ty), title, fill=(20,20,20), font=title_font)

    # Body as wrapped bullets
    y = ty + th + 20
    max_w = width - 2*pad
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            y += 10
            continue
        # prefix dash if missing for list-like feel
        if not (line.startswith('-') or line.startswith('•')):
            line = f"- {line}"
        words = line.split()
        cur = ""
        while words:
            w = words.pop(0)
            test = w if not cur else cur + " " + w
            try:
                tb = draw.textbbox((0, 0), test, font=body_font)
                tw = tb[2]-tb[0]
            except Exception:
                tw = len(test) * 10
            if tw <= max_w:
                cur = test
            else:
                if cur:
                    draw.text((pad, y), cur, fill=text_color, font=body_font)
                    y += 36
                    cur = w
                else:
                    draw.text((pad, y), w, fill=text_color, font=body_font)
                    y += 36
        if cur:
            draw.text((pad, y), cur, fill=text_color, font=body_font)
            y += 42
    img.save(out_path)


# ---- Request models ----
class LiteTopic(BaseModel):
    topic: str
    minutes_per_day: int = 2

class CreateLitesRequest(BaseModel):
    topics: List[LiteTopic]
    user_email: Optional[str] = None
    user_id: Optional[int] = None


# ---- Topics persistence (raw SQL) ----
class LitesTopicsUpsertRequest(BaseModel):
    user_id: int
    topics: List[LiteTopic]

class LitesTopicOut(BaseModel):
    topic_id: int
    topic: str
    minutes_per_day: int
    active: bool

def _ensure_lites_tables(db) -> None:
    db.execute(text(
        """
        CREATE TABLE IF NOT EXISTS public.lites_topics (
            topic_id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES public.users(user_id) ON DELETE CASCADE,
            topic TEXT NOT NULL,
            minutes_per_day INTEGER NOT NULL DEFAULT 2,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_on TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_on TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_lites_topics_user_topic ON public.lites_topics(user_id, topic);
        """
    ))
    db.commit()

def _ensure_sub_topics_table(db) -> None:
    """Ensure the configured sub-topics table exists with expected schema and unique constraint."""
    try:
        # Only allow safe known table names
        table = SUB_TOPICS_TABLE
        if table not in {"public.lites_sub_topics", os.getenv("LITES_SUB_TOPICS_TABLE", "public.lites_sub_topics")}:
            table = "public.lites_sub_topics"
        # Create table and unique index if they don't exist
        db.execute(text(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id SERIAL PRIMARY KEY,
                topic_id INTEGER REFERENCES public.lites_topics(topic_id) ON DELETE CASCADE,
                sub_topic TEXT NOT NULL,
                created_on TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_lites_sub_topics_topic_sub
                ON {table} (topic_id, sub_topic);
            -- Ensure 'id' column has a default/identity even if the table pre-existed without it
            DO $$
            DECLARE
                v_schema text := split_part('{table}', '.', 1);
                v_table  text := split_part('{table}', '.', 2);
                v_has_default boolean;
            BEGIN
                SELECT (column_default IS NOT NULL) INTO v_has_default
                FROM information_schema.columns
                WHERE table_schema = v_schema AND table_name = v_table AND column_name = 'id'
                LIMIT 1;
                IF NOT COALESCE(v_has_default, false) THEN
                    BEGIN
                        EXECUTE format('ALTER TABLE %I.%I ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY', v_schema, v_table);
                    EXCEPTION WHEN duplicate_object THEN
                        -- already identity/default; ignore
                        NULL;
                    END;
                END IF;
            END $$;
            """
        ))
        db.commit()
    except Exception as e:
        logger.warning(f"ensure sub-topics table failed: {e}")

def _get_or_create_topic_id(db, user_id: int, topic: str, minutes_per_day: int) -> Optional[int]:
    """Ensure a row exists in public.lites_topics for (user_id, topic) and return its topic_id."""
    try:
        _ensure_lites_tables(db)
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
        # Fallback select
        row2 = db.execute(text(
            """
            SELECT topic_id FROM public.lites_topics WHERE user_id = :uid AND topic = :topic
            """
        ), {"uid": int(user_id), "topic": topic}).mappings().first()
        return int(row2["topic_id"]) if row2 and "topic_id" in row2 else None  # type: ignore[index]
    except Exception as e:
        logger.warning(f"get/create lites_topics failed: {e}")
        return None

@router.get("/topics")
async def get_lites_topics(user_id: Optional[int] = None):
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    db = Session()
    try:
        _ensure_lites_tables(db)
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
async def delete_lites_topic(user_id: Optional[int] = None, topic_id: Optional[int] = None):
    """Soft-unsubscribe a topic by marking active=false in public.lites_topics."""
    if not user_id or not topic_id:
        raise HTTPException(status_code=400, detail="user_id and topic_id are required")
    db = Session()
    try:
        _ensure_lites_tables(db)
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
        logger.error(f"delete_lites_topic error: {e}")
        raise HTTPException(status_code=500, detail="Failed to unsubscribe topic")
    finally:
        db.close()

@router.post("/topics")
async def upsert_lites_topics(req: LitesTopicsUpsertRequest):
    if not req.topics:
        raise HTTPException(status_code=400, detail="topics cannot be empty")
    # normalize
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
        _ensure_lites_tables(db)
        # Upsert each topic; ON CONFLICT on (user_id, topic)
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

        # Ensure a default sub-topic row exists for each topic (idempotent)
        for it in items:
            try:
                tid = _get_or_create_topic_id(db, int(req.user_id), it["topic"], int(it["minutes_per_day"]))
                if tid is not None:
                    # Use the base topic string as an initial sub-topic entry
                    _insert_lite_sub_topic(db, int(tid), it["topic"])
            except Exception as e:
                logger.warning(f"sub-topic insert during upsert ignored for topic='{it['topic']}': {e}")
                try:
                    db.rollback()
                except Exception:
                    pass

        # Return updated list
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


@router.post("")
async def create_lites(req: CreateLitesRequest, bg: BackgroundTasks):
    if not req or not isinstance(req.topics, list) or len(req.topics) == 0:
        raise HTTPException(status_code=400, detail="At least one topic is required")

    # Normalize topics
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
            base_dir = Path("generated")
            base_dir.mkdir(parents=True, exist_ok=True)
            for item in items:
                tp = item["topic"]
                mpd = int(item.get("minutes_per_day", 2))
                # Plan one subtopic for this topic
                subtopics = _gemini_plan_subtopics(tp, mpd, count=1)
                for sub in subtopics:
                    if not isinstance(sub, str) or not sub.strip():
                        continue
                    combined = f"{tp} - {sub.strip()}"
                    safe = _sanitize_filename(combined)
                    out_dir = base_dir / f"lites_{safe}_{ts}"
                    dirs = _ensure_dirs(out_dir)
                    # 1) Slides + 2) Narrations + tags via Gemini
                    logger.info(f"Generating slides/narrations/tags with Gemini for: {combined}")
                    gem = _gemini_generate(combined)
                    # Build markdown slides from structured slides
                    structured_slides = gem.get("slides", [])
                    slides: List[str] = []
                    for sl in structured_slides:
                        title = (sl.get("title") or "Slide").strip()
                        bullets = sl.get("bullets") or []
                        bullets = [b for b in bullets if isinstance(b, str) and b.strip()]
                        body = "\n".join([f"- {b.strip()}" if not b.strip().startswith('-') else b.strip() for b in bullets])
                        slides.append(f"## {title}\n{body}".strip())

                    narr = gem.get("narrations") or []
                    if not isinstance(narr, list):
                        narr = []
                    # length match safeguard
                    if len(narr) < len(slides):
                        narr.extend([f"This slide covers {combined}. Focus on the key points."] * (len(slides)-len(narr)))
                    narr = narr[:len(slides)]
                    # Persist tags
                    try:
                        tags = gem.get("tags") or []
                        (out_dir / "tags.json").write_text(json.dumps(tags, ensure_ascii=False, indent=2), encoding='utf-8')
                    except Exception as e:
                        logger.warning(f"failed to write tags.json: {e}")

                    # Append endcard
                    slides.append("## Johnify\n")
                    narr.append("thanks for learning")

                    # Dedup check using canonical payload
                    canon_payload = _canonicalize_slides(structured_slides, narr, tags)
                    dbcheck = Session()
                    try:
                        if user_id is not None and _is_duplicate_content(dbcheck, int(user_id), combined, canon_payload.get("content_hash", "")):
                            logger.info(f"Skipped duplicate lites content for user={user_id} topic='{combined}'")
                            try:
                                dbcheck.close()
                            except Exception:
                                pass
                            # still insert sub-topic link to track coverage
                            try:
                                dbt = Session()
                                tid = _get_or_create_topic_id(dbt, int(user_id), tp, mpd)
                                if tid is not None:
                                    _insert_lite_sub_topic(dbt, int(tid), combined)
                            except Exception:
                                pass
                            finally:
                                try:
                                    dbt.close()
                                except Exception:
                                    pass
                            continue
                    finally:
                        try:
                            dbcheck.close()
                        except Exception:
                            pass

                    # 3) Save slides.md with narration comments
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
                                # For normal content slides, add placeholder bullets if none exist.
                                # But for the branding end slide ('## Johnify'), do NOT add any bullets.
                                has_bullets = any(line.strip().startswith('-') for line in s.split('\n'))
                                is_brand_endcard = any(
                                    (ln.strip().lower().startswith('## johnify')) for ln in s.split('\n')[:3]
                                )
                                if not has_bullets and not is_brand_endcard:
                                    s += "\n- Point 1\n- Point 2\n- Point 3"
                                s = '\n'.join([ln for ln in s.split('\n') if ln.strip()])
                                f.write(f"{s}\n\n<!-- NARRATION: {n} -->\n")
                    except Exception as e:
                        logger.error(f"failed to write slides.md: {e}")

                    # 4) Render images
                    images_dir = dirs["images"]
                    try:
                        title_png = images_dir / "slide_000.png"
                        _create_title_image(combined, title_png)
                        # parse slides.md contents (excluding frontmatter) into slide blocks
                        raw = md_file.read_text(encoding='utf-8') if md_file.exists() else ""
                        raw = raw.split('---', 2)
                        content_only = raw[2] if len(raw) >= 3 else raw[0]
                        blocks = [b.strip() for b in content_only.split('---') if b.strip()]
                        # remove narration comments from render text
                        import re as _re
                        rendered = []
                        for b in blocks:
                            b2 = _re.sub(r'<!--.*?-->', '', b, flags=_re.DOTALL).strip()
                            # extract title if present
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
                                _draw_text_slide(ti, body, outp, mode="brand")
                            else:
                                _draw_text_slide(ti, body, outp)
                    except Exception as e:
                        logger.error(f"image render error: {e}")

                    # 5) Audio from narrations
                    audio_dir = dirs["audio"]
                    audio_files: List[str] = []
                    image_files: List[str] = []
                    try:
                        tts_dir = _narrations_to_mp3(narr, str(audio_dir))
                        audio_files = sorted([str(p) for p in Path(tts_dir).glob('*.mp3')])
                        # prepend silent if title exists
                        title_png = images_dir / "slide_000.png"
                        if title_png.exists():
                            silent_mp3 = Path(tts_dir) / "s000.mp3"
                            if not silent_mp3.exists() or os.path.getsize(silent_mp3) == 0:
                                subprocess.run([
                                    'ffmpeg','-y','-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100','-t','1.5','-c:a','libmp3lame',str(silent_mp3)
                                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            audio_files = sorted([str(p) for p in Path(tts_dir).glob('*.mp3')])
                    except Exception as e:
                        logger.error(f"audio generation error: {e}")

                    # 6) Pair images and audio
                    try:
                        image_files = sorted([str(p) for p in images_dir.glob('*.png')])
                        min_len = min(len(image_files), len(audio_files))
                        if min_len == 0:
                            raise ValueError("no images/audio")
                        image_files = image_files[:min_len]
                        audio_files = audio_files[:min_len]
                    except Exception as e:
                        logger.error(f"pairing error: {e}")

                    # 7) Stitch video
                    video_path = out_dir / f"lites_{safe}_{ts}.mp4"
                    try:
                        _stitch_images_and_audio_to_video(
                            img_dir=Path(image_files[0]).parent,
                            aud_dir=Path(audio_files[0]).parent,
                            out_mp4=video_path
                        )
                    except Exception as e:
                        logger.error(f"video stitch error: {e}")

                    # 8) Thumbnail
                    try:
                        thumb = out_dir / "thumbnail.jpg"
                        if (images_dir / "slide_000.png").exists():
                            Image.open(images_dir / "slide_000.png").convert('RGB').save(thumb, format='JPEG', quality=88)
                        elif image_files:
                            Image.open(image_files[0]).convert('RGB').save(thumb, format='JPEG', quality=88)
                    except Exception as e:
                        logger.error(f"thumbnail error: {e}")

                    # 9) Publish SSE + Persist DB + Insert sub-topic
                    try:
                        if user_id is not None:
                            # Determine generated root similar to /status
                            ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
                            IS_PRODUCTION = ENVIRONMENT == "production"
                            if IS_PRODUCTION:
                                base_root = Path("/tmp")
                            else:
                                base_root = Path(__file__).resolve().parent.parent.parent
                            GENERATED_ROOT = (base_root / "generated").resolve()

                            base_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip('/')
                            # Compute rel paths and URLs
                            try:
                                rel_video = video_path.resolve().relative_to(GENERATED_ROOT).as_posix()
                                video_url = f"{base_url}/videos/{rel_video}"
                            except Exception:
                                rel_video = video_path.as_posix()
                                video_url = ""
                            thumb_path = out_dir / "thumbnail.jpg"
                            thumbnail_url = ""
                            try:
                                if thumb_path.exists():
                                    rel_thumb = thumb_path.resolve().relative_to(GENERATED_ROOT).as_posix()
                                    thumbnail_url = f"{base_url}/videos/{rel_thumb}"
                            except Exception:
                                pass

                            post_path = f"generated/{rel_video}"

                            # Persist user_posts
                            dbp = Session()
                            try:
                                _persist_user_post(dbp, user_id=int(user_id), post_path=post_path, post_topic=combined, tags=tags, content_json=canon_payload)
                            finally:
                                dbp.close()

                            # Ensure parent topic exists and insert sub-topic row
                            dbt = Session()
                            try:
                                tid = _get_or_create_topic_id(dbt, int(user_id), tp, mpd)
                                if tid is not None:
                                    _insert_lite_sub_topic(dbt, int(tid), combined)
                            finally:
                                dbt.close()

                            payload = {
                                "event": "lite_video",
                                "topic": combined,
                                "dir": f"generated/{out_dir.name}",
                                "post_path": post_path,
                                "video_url": video_url,
                                "thumbnail_url": thumbnail_url,
                            }
                            # Publish SSE: if running loop exists, create_task; else run directly
                            import asyncio as _aio
                            try:
                                _ = _aio.get_running_loop()
                                _aio.create_task(broker.publish_json(int(user_id), "lite_video", payload))
                            except RuntimeError:
                                _aio.run(broker.publish_json(int(user_id), "lite_video", payload))
                    except Exception as e:
                        logger.warning(f"post-publish failed: {e}")
        except Exception as e:
            logger.exception(f"background error: {e}")

    # Precompute timestamp and expected output directories to return as job IDs
    ts = int(time.time())
    jobs: List[Dict[str, str]] = []
    for item in topics:
        safe = _sanitize_filename(item["topic"])
        dir_rel = f"generated/lites_{safe}_{ts}"
        jobs.append({
            "topic": item["topic"],
            "dir": dir_rel,
        })

    bg.add_task(_run, topics, req.user_email, req.user_id, ts)
    return {"status": "started", "message": "Lite generation started.", "count": len(topics), "jobs": jobs}


@router.get("/diag")
async def lites_diag():
    """Minimal diagnostics for env and dependencies.
    Returns ffmpeg/ffprobe availability and Google TTS client init status.
    """
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

    # Mask obvious file paths in error for safety
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
async def lites_status(request: Request):
    """Check readiness of one or more Lites jobs.
    Query params: dir=<generated/subdir> (can repeat). Example: dir=generated/lites_topic_123
    Returns list of jobs with status and URLs when available.
    """
    try:
        # Collect all 'dir' params
        query_params = request.query_params.getlist("dir") if hasattr(request, "query_params") else []
        dirs_in = [d for d in query_params if isinstance(d, str) and d.strip()]
        if not dirs_in:
            raise HTTPException(status_code=400, detail="Provide one or more 'dir' query parameters")

        # Resolve generated root similar to videos.py
        ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
        IS_PRODUCTION = ENVIRONMENT == "production"
        if IS_PRODUCTION:
            base_root = Path("/tmp")
        else:
            base_root = Path(__file__).resolve().parent.parent.parent
        GENERATED_ROOT = (base_root / "generated").resolve()

        base_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip('/')

        results: List[Dict[str, Any]] = []
        for d in dirs_in:
            # Normalize incoming dir to be relative under generated/
            norm = d.replace("\\", "/").strip()
            if norm.startswith("generated/"):
                norm = norm[len("generated/"):]
            norm = norm.lstrip("/")
            abs_dir = (GENERATED_ROOT / norm).resolve()

            # Security: ensure within GENERATED_ROOT
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
                    # Find first mp4
                    mp4s = sorted([p for p in abs_dir.glob("*.mp4")])
                    if mp4s:
                        rel = mp4s[0].relative_to(GENERATED_ROOT).as_posix()
                        video_url = f"{base_url}/videos/{rel}"
                        status = "completed"
                        # thumbnail
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
        logger.error(f"lites_status error: {e}")
        raise HTTPException(status_code=500, detail="Failed to check status")


@router.get("/stream")
async def lites_stream(user_id: Optional[int] = None):
    """
    SSE stream for real-time lites updates. Requires a user_id to scope events.
    Usage from browser: new EventSource(`/api/lites/stream?user_id=123`)
    """
    if user_id is None:
        raise HTTPException(status_code=400, detail="user_id is required")
    return StreamingResponse(broker.subscribe(int(user_id)), media_type="text/event-stream")


# ---- Planning and sequential generation with persistence ----
class GenerateLitesRequest(BaseModel):
    user_id: int
    topic_ids: Optional[List[int]] = None  # if omitted, all active topics
    max_per_topic: int = 1  # how many subtopics to generate today (default 1)

def _gemini_plan_subtopics(topic: str, minutes_per_day: int, count: int = 1) -> List[str]:
    """Plan concise subtopics for 'today'. Fallback to the topic itself."""
    try:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY not set")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("models/gemini-2.5-flash-lite")
        prompt = (
            "Return ONLY JSON of the form {\"subtopics\": [..]} where each item is a concise subtopic title.\n"
            f"Create {max(1, int(count))} focused subtopic(s) for today's {minutes_per_day} minutes on: {topic}"
        )
        resp = model.generate_content(prompt)
        txt = getattr(resp, "text", "") or str(resp)
        data = {}
        try:
            data = json.loads(txt)
        except Exception:
            import re as _re
            m = _re.search(r"\{[\s\S]*\}", txt)
            if m:
                try:
                    data = json.loads(m.group(0))
                except Exception:
                    pass
        subs = data.get("subtopics") if isinstance(data, dict) else None
        if not isinstance(subs, list) or not subs:
            return [topic]
        out = []
        for s in subs[:count]:
            if isinstance(s, str) and s.strip():
                out.append(s.strip())
        return out or [topic]
    except Exception:
        return [topic]

def _insert_lite_sub_topic(db, topic_id: int, sub_topic: str) -> None:
    """Insert a sub-topic row into the configured sub-topics table.
    Table is expected to already exist with columns: id PK, topic_id INT (FK to lites_topics.topic_id), sub_topic TEXT, created_on TIMESTAMP.
    """
    try:
        _ensure_sub_topics_table(db)
        # Note: table name cannot be bound as a parameter; it's taken from env and static in-process.
        sql = f"INSERT INTO {SUB_TOPICS_TABLE} (topic_id, sub_topic) VALUES (:tid, :stxt) ON CONFLICT (topic_id, sub_topic) DO NOTHING"
        logger.info(f"inserting lites sub-topic: table={SUB_TOPICS_TABLE}, topic_id={int(topic_id)}, sub_topic={sub_topic}")
        db.execute(text(sql), {"tid": int(topic_id), "stxt": sub_topic})
        db.commit()
        logger.info("lites sub-topic insert ok (or already existed)")
    except Exception as e:
        logger.exception(f"insert into sub-topics failed (table={SUB_TOPICS_TABLE}, topic_id={topic_id}, sub_topic={sub_topic}): {e}")
        raise

def _persist_user_post(db, user_id: int, post_path: str, post_topic: str, tags: Optional[List[str]], content_json: Optional[Dict[str, Any]] = None):
    try:
        db.execute(text(
            """
            INSERT INTO public.user_posts (user_id, post_path, post_topic, type, public, tags, created_on, content)
            VALUES (:uid, :ppath, :ptopic, 'lites', TRUE, CAST(:tags AS JSONB), NOW(), :content)
            """
        ), {
            "uid": int(user_id),
            "ppath": post_path,
            "ptopic": post_topic,
            "tags": json.dumps(tags or []),
            "content": json.dumps(content_json, ensure_ascii=False) if content_json is not None else None,
        })
        db.commit()
    except Exception as e:
        logger.warning(f"persist user_posts with content failed, retrying without content: {e}")
        try:
            # Fallback for databases that don't yet have the 'content' column
            db.rollback()
        except Exception:
            pass
        try:
            db.execute(text(
                """
                INSERT INTO public.user_posts (user_id, post_path, post_topic, type, public, tags, created_on)
                VALUES (:uid, :ppath, :ptopic, 'lites', TRUE, CAST(:tags AS JSONB), NOW())
                """
            ), {
                "uid": int(user_id),
                "ppath": post_path,
                "ptopic": post_topic,
                "tags": json.dumps(tags or []),
            })
            db.commit()
        except Exception as e2:
            logger.warning(f"persist user_posts fallback failed: {e2}")

def _canonicalize_slides(structured_slides: List[Dict[str, Any]], narr: List[str], tags: List[str]) -> Dict[str, Any]:
    """Return a stable payload for storage and hashing. Excludes volatile fields like timestamps.
    Adds a content_hash field.
    """
    # Normalize slides: keep only title and bullets strings
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

def _is_duplicate_content(db, user_id: int, post_topic: str, content_hash: str) -> bool:
    """Check recent lites posts for the same user for matching content_hash stored in content JSON (as text).
    Note: We intentionally do not restrict by topic to avoid duplicates across different subtopic titles.
    """
    try:
        rows = db.execute(text(
            """
            SELECT content
            FROM public.user_posts
            WHERE user_id = :uid AND type = 'lites' AND content IS NOT NULL
            ORDER BY created_on DESC
            LIMIT 50
            """
        ), {"uid": int(user_id)}).fetchall()
        for r in rows:
            try:
                ctext = r[0] if isinstance(r, (list, tuple)) else (getattr(r, "content", None) if r is not None else None)
                if not ctext:
                    continue
                obj = json.loads(ctext)
                if isinstance(obj, dict) and obj.get("content_hash") == content_hash:
                    return True
            except Exception:
                continue
        return False
    except Exception as e:
        logger.warning(f"duplicate check failed: {e}")
        return False

def _generate_single_lite(user_id: int, user_email: Optional[str], topic: str) -> Dict[str, Any]:
    ts = int(time.time())
    base_dir = Path("generated")
    base_dir.mkdir(parents=True, exist_ok=True)
    safe = _sanitize_filename(topic)
    out_dir = base_dir / f"lites_{safe}_{ts}"
    dirs = _ensure_dirs(out_dir)
    # slides/narr/tags
    gem = _gemini_generate(topic)
    structured_slides = gem.get("slides", [])
    narr = gem.get("narrations") or []
    tags = gem.get("tags") or []
    slides: List[str] = []
    for sl in structured_slides:
        title = (sl.get("title") or "Slide").strip()
        bullets = sl.get("bullets") or []
        bullets = [b for b in bullets if isinstance(b, str) and b.strip()]
        body = "\n".join([f"- {b.strip()}" if not b.strip().startswith('-') else b.strip() for b in bullets])
        slides.append(f"## {title}\n{body}".strip())
    if len(narr) < len(slides):
        narr.extend([f"This slide covers {topic}. Focus on the key points."] * (len(slides)-len(narr)))
    narr = narr[:len(slides)]
    try:
        (out_dir / "tags.json").write_text(json.dumps(tags, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass
    slides.append("## Johnify\n")
    narr.append("thanks for learning")

    # Dedup check using canonical payload before heavy work
    canon_payload = _canonicalize_slides(structured_slides, narr, tags)
    dbcheck = Session()
    try:
        if _is_duplicate_content(dbcheck, int(user_id), topic, canon_payload.get("content_hash", "")):
            logger.info(f"Skipped duplicate lites content for user={user_id} topic='{topic}'")
            return {"status": "skipped", "reason": "duplicate", "topic": topic}
    finally:
        dbcheck.close()

    # slides.md
    md_file = out_dir / "slides.md"
    with md_file.open('w', encoding='utf-8') as f:
        f.write("---\nmarp: true\ntheme: default\npaginate: true\n---\n\n")
        for i, (s, n) in enumerate(zip(slides, narr)):
            if i > 0:
                f.write("\n---\n\n")
            s = (s or "").strip()
            if s and not any(line.strip().startswith('#') for line in s.split('\n')[:3]):
                s = f"## Slide {i+1}\n" + s
            if not any(line.strip().startswith('-') for line in s.split('\n')):
                s += "\n- Point 1\n- Point 2\n- Point 3"
            s = '\n'.join([ln for ln in s.split('\n') if ln.strip()])
            f.write(f"{s}\n\n<!-- NARRATION: {n} -->\n")

    # render images
    images_dir = dirs["images"]
    title_png = images_dir / "slide_000.png"
    _create_title_image(topic, title_png)
    raw = md_file.read_text(encoding='utf-8')
    raw_parts = raw.split('---', 2)
    content_only = raw_parts[2] if len(raw_parts) >= 3 else raw_parts[0]
    blocks = [b.strip() for b in content_only.split('---') if b.strip()]
    import re as _re
    rendered = []
    for b in blocks:
        b2 = _re.sub(r'<!--.*?-->', '', b, flags=_re.DOTALL).strip()
        title_line = ""
        for ln in b2.split('\n')[:3]:
            if ln.strip().startswith('## '):
                title_line = ln.strip()[3:].strip(); break
        if not title_line:
            title_line = "Slide"
        body = '\n'.join([ln for ln in b2.split('\n') if not ln.strip().startswith('## ')])
        rendered.append((title_line, body))
    for idx, (ti, body) in enumerate(rendered, 1):
        outp = images_dir / f"slide_{idx:03d}.png"
        _draw_text_slide(ti, body, outp)

    # audio
    audio_dir = dirs["audio"]
    tts_dir = _narrations_to_mp3(narr, str(audio_dir))
    audio_files = sorted([str(p) for p in Path(tts_dir).glob('*.mp3')])
    if title_png.exists():
        silent_mp3 = Path(tts_dir) / "s000.mp3"
        if not silent_mp3.exists() or os.path.getsize(silent_mp3) == 0:
            subprocess.run(['ffmpeg','-y','-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100','-t','1.5','-c:a','libmp3lame',str(silent_mp3)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        audio_files = sorted([str(p) for p in Path(tts_dir).glob('*.mp3')])

    # pair
    image_files = sorted([str(p) for p in images_dir.glob('*.png')])
    min_len = min(len(image_files), len(audio_files))
    image_files = image_files[:min_len]
    audio_files = audio_files[:min_len]

    # stitch
    video_path = out_dir / f"lites_{safe}_{ts}.mp4"
    _stitch_images_and_audio_to_video(
        img_dir=Path(image_files[0]).parent,
        aud_dir=Path(audio_files[0]).parent,
        out_mp4=video_path,
    )

    # thumbnail
    thumb = out_dir / "thumbnail.jpg"
    if (images_dir / "slide_000.png").exists():
        Image.open(images_dir / "slide_000.png").convert('RGB').save(thumb, format='JPEG', quality=88)
    elif image_files:
        Image.open(image_files[0]).convert('RGB').save(thumb, format='JPEG', quality=88)

    # URLs and post_path
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    IS_PRODUCTION = ENVIRONMENT == "production"
    base_root = Path("/tmp") if IS_PRODUCTION else Path(__file__).resolve().parent.parent.parent
    GENERATED_ROOT = (base_root / "generated").resolve()
    base_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip('/')
    rel_video = video_path.resolve().relative_to((GENERATED_ROOT)).as_posix()
    video_url = f"{base_url}/videos/{rel_video}"
    thumbnail_url = ""
    if thumb.exists():
        rel_thumb = thumb.resolve().relative_to(GENERATED_ROOT).as_posix()
        thumbnail_url = f"{base_url}/videos/{rel_thumb}"
    post_path = f"generated/{rel_video}"

    # persist DB
    db = Session()
    try:
        _persist_user_post(db, user_id=user_id, post_path=post_path, post_topic=topic, tags=tags, content_json=canon_payload)
    finally:
        db.close()

    # publish SSE
    payload = {
        "event": "lite_video",
        "topic": topic,
        "dir": f"generated/{out_dir.name}",
        "post_path": post_path,
        "video_url": video_url,
        "thumbnail_url": thumbnail_url,
    }
    import asyncio as _aio
    try:
        _ = _aio.get_running_loop()
        _aio.create_task(broker.publish_json(int(user_id), "lite_video", payload))
    except RuntimeError:
        _aio.run(broker.publish_json(int(user_id), "lite_video", payload))

    return payload

@router.post("/generate")
async def generate_lites(req: GenerateLitesRequest, bg: BackgroundTasks):
    # Fetch active topics for the user (optionally filter by topic_ids)
    db = Session()
    try:
        _ensure_lites_tables(db)
        if req.topic_ids and len(req.topic_ids) > 0:
            rows = db.execute(text(
                """
                SELECT topic_id, topic, minutes_per_day
                FROM public.lites_topics
                WHERE user_id = :uid AND active = TRUE AND topic_id = ANY(:tids)
                ORDER BY topic_id ASC
                """
            ), {"uid": int(req.user_id), "tids": req.topic_ids}).mappings().all()
        else:
            rows = db.execute(text(
                """
                SELECT topic_id, topic, minutes_per_day
                FROM public.lites_topics
                WHERE user_id = :uid AND active = TRUE
                ORDER BY topic_id ASC
                """
            ), {"uid": int(req.user_id)}).mappings().all()
    finally:
        db.close()

    if not rows:
        raise HTTPException(status_code=400, detail="No topics found for user")

    # Plan subtopics per topic now (synchronous, lightweight)
    # Build sub_topic as "{topic} + {sub}" and keep parent topic_id
    plans: List[Dict[str, Any]] = []
    for r in rows:
        parent_topic = r["topic"]
        parent_topic_id = int(r["topic_id"]) if "topic_id" in r else None
        mpd = int(r["minutes_per_day"])
        subs = _gemini_plan_subtopics(parent_topic, mpd, count=max(1, int(req.max_per_topic)))
        for s in subs:
            if isinstance(s, str) and s.strip():
                sub_topic = f"{parent_topic} - {s.strip()}"
                plans.append({
                    "topic_id": parent_topic_id,
                    "sub_topic": sub_topic,
                })

    # Run sequentially in background
    def _seq_run(user_id: int, items: List[Dict[str, Any]]):
        for it in items:
            try:
                # Generate video for the sub_topic
                topic_text = it.get("sub_topic") or ""
                if not isinstance(topic_text, str) or not topic_text.strip():
                    continue
                _generate_single_lite(user_id=user_id, user_email=None, topic=topic_text)  # emits SSE and persists

                # On success, persist sub-topic row (if topic_id available)
                tid = it.get("topic_id")
                if tid is not None:
                    db2 = Session()
                    try:
                        _insert_lite_sub_topic(db2, int(tid), topic_text)
                    finally:
                        db2.close()
            except Exception as e:
                logger.exception(f"sequential generation failed for {it}: {e}")

    bg.add_task(_seq_run, int(req.user_id), plans)
    return {"status": "started", "planned": len(plans)}
