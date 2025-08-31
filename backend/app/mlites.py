from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
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

# Mobile Lites (mlites) router
router = APIRouter(prefix="/api/mlites", tags=["mlites"])

# Logger
logger = logging.getLogger("mlites")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] mlites: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# SSE broker
try:
    from .services.sse_broker import broker
except Exception:
    from .services.sse_broker import broker  # type: ignore

# ---- Helpers ----

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


def _create_title_image(text: str, out_path: Path, width: int = 1080, height: int = 1920) -> None:
    img = Image.new('RGB', (width, height), color=(26, 28, 34))
    draw = ImageDraw.Draw(img)
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

    brand = "johnify mlites"
    try:
        bw = text_w(brand, font_small)
    except Exception:
        bw = len(brand) * 10
    bx = width - bw - 24
    by = height - 24 - 36
    draw.text((bx + 2, by + 2), brand, fill=(0, 0, 0), font=font_small)
    draw.text((bx, by), brand, fill=(200, 200, 200), font=font_small)

    img.save(out_path)


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


def _narrations_to_mp3(narrations: List[str], out_dir: str) -> Path:
    from google.cloud import texttospeech
    out_p = Path(out_dir)
    if out_p.exists():
        import shutil
        shutil.rmtree(out_p)
    out_p.mkdir(parents=True, exist_ok=True)
    client = texttospeech.TextToSpeechClient()
    voice = texttospeech.VoiceSelectionParams(
        language_code="en-US",
        name="en-US-Neural2-F",
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.05,
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
            '-vf','fps=30,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1',
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
            silent = temp_dir / 'silent.mp3'
            subprocess.run(['ffmpeg','-y','-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100','-t','5','-c:a','libmp3lame',str(silent)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            mp3s = [silent] * len(imgs)
        pair_n = min(len(imgs), len(mp3s))
        max_total = 89.0  # hard cap under 90s
        min_total = 60.0  # ensure at least 60s
        min_per = 1.5
        per_cap = max(min_per, max_total / float(max(1, pair_n)))
        per_cap = min(per_cap, 18.0)
        segs = []
        total_used = 0.0
        for i in range(pair_n):
            seg = temp_dir / f"seg_{i+1:03d}.mp4"
            orig = _get_audio_duration(mp3s[i])
            use_dur = min(per_cap, max(min_per, orig))
            _create_slide_video(imgs[i], mp3s[i], seg, duration_override=use_dur)
            segs.append(seg)
            total_used += float(use_dur)
        # If total duration is below 60s, append a final silent segment using last image
        if total_used < min_total:
            try:
                need = float(min_total - total_used)
                need = max(0.5, min(need, 15.0))
                last_img = imgs[min(pair_n - 1, len(imgs) - 1)] if pair_n > 0 else imgs[0]
                silent_mp3 = temp_dir / 'pad_silent.mp3'
                subprocess.run(['ffmpeg','-y','-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100','-t',str(round(need,2)),'-c:a','libmp3lame',str(silent_mp3)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
):
    img = Image.new('RGB', (width, height), color=(245, 246, 250))
    draw = ImageDraw.Draw(img)
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
        img.save(out_path)
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
    max_lines = 4  # reels-like: fewer lines
    lines_rendered = 0
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            y += 8
            continue
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
    img.save(out_path)


# ---- Gemini content generation (mobile-optimized) ----

def _gemini_generate_mobile(topic: str) -> Dict[str, Any]:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set for Gemini")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("models/gemini-2.5-flash-lite")
    prompt = (
        "You generate mobile-first, vertical short video slides. Return ONLY strict JSON with keys: slides, narrations, tags.\n"
        "- slides: array of 4-6 objects: {title: string, bullets: array of 2-3 bullets, EACH bullet 1-4 words max; emojis allowed sparingly}. Keep on-screen text minimal.\n"
        "- narrations: array of same length; EACH narration is 2-3 short sentences (total 20-45 words), engaging and explanatory.\n"
        "- tags: array of 5-10 lowercase single-word keywords.\n"
        f"Topic: {topic}\n"
    )
    resp = model.generate_content(prompt)
    text = ""
    try:
        text = resp.text or ""
    except Exception:
        text = str(resp)

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
        narr = [f"A quick, engaging overview of {topic}. Here's what matters most. Keep watching for the essentials."] * len(slides)
    narr = narr[:len(slides)]
    if not isinstance(tags, list) or len(tags) == 0:
        tags = [topic.split(" ")[0].lower(), "basics", "mobile"]
    return {"slides": slides, "narrations": narr, "tags": tags}


# ---- Request models ----
class MLiteTopic(BaseModel):
    topic: str
    minutes_per_day: int = 2


class CreateMLitesRequest(BaseModel):
    topics: List[MLiteTopic]
    user_email: Optional[str] = None
    user_id: Optional[int] = None


@router.post("")
async def create_mlites(req: CreateMLitesRequest, bg: BackgroundTasks):
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
            base_dir = Path("generated")
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

                combined = tp  # keep simple for now
                safe = _sanitize_filename(combined)
                out_dir = base_dir / f"mlites_{safe}_{ts}"
                dirs = _ensure_dirs(out_dir)

                # 1) Slides + 2) Narrations + tags via Gemini (mobile optimized)
                logger.info(f"[mlites] Generating mobile content for: {combined}")
                gem = _gemini_generate_mobile(combined)

                # Build markdown slides
                structured = gem.get("slides", [])
                # Best-effort derive a sub-topic from first non-brand slide title
                derived_sub_topic = None
                try:
                    if isinstance(structured, list) and structured:
                        t0 = (structured[0].get("title") or "").strip()
                        if t0 and t0.lower() != "johnify":
                            derived_sub_topic = t0[:255]
                except Exception:
                    derived_sub_topic = None
                # If the derived sub-topic is effectively the same as the main topic, ignore it
                try:
                    if derived_sub_topic and derived_sub_topic.strip().lower() == tp.strip().lower():
                        derived_sub_topic = None
                except Exception:
                    pass
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
                    title_png = images_dir / "slide_000.png"
                    _create_title_image(combined, title_png, 1080, 1920)
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
                            _draw_text_slide(ti, body, outp, width=1080, height=1920)
                except Exception as e:
                    logger.error(f"[mlites] image render error: {e}")

                # 5) TTS
                audio_dir = dirs["audio"]
                audio_files: List[str] = []
                image_files: List[str] = []
                try:
                    tts_dir = _narrations_to_mp3(narr, str(audio_dir))
                    audio_files = sorted([str(p) for p in Path(tts_dir).glob('*.mp3')])
                    title_png = images_dir / "slide_000.png"
                    if title_png.exists():
                        silent_mp3 = Path(tts_dir) / "s000.mp3"
                        if not silent_mp3.exists() or os.path.getsize(silent_mp3) == 0:
                            subprocess.run(['ffmpeg','-y','-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100','-t','1.25','-c:a','libmp3lame',str(silent_mp3)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

                # 8) Thumbnail
                try:
                    thumb = out_dir / "thumbnail.jpg"
                    if (images_dir / "slide_000.png").exists():
                        Image.open(images_dir / "slide_000.png").convert('RGB').save(thumb, format='JPEG', quality=88)
                    elif image_files:
                        Image.open(image_files[0]).convert('RGB').save(thumb, format='JPEG', quality=88)
                except Exception as e:
                    logger.error(f"[mlites] thumbnail error: {e}")

                # 9) Publish SSE + Persist DB
                try:
                    if user_id is not None:
                        ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
                        IS_PRODUCTION = ENVIRONMENT == "production"
                        base_root = Path("/tmp") if IS_PRODUCTION else Path(__file__).resolve().parent.parent.parent
                        GENERATED_ROOT = (base_root / "generated").resolve()
                        base_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip('/')
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
                        import asyncio as _aio
                        try:
                            _ = _aio.get_running_loop()
                            _aio.create_task(broker.publish_json(int(user_id), "mlite_video", payload))
                        except RuntimeError:
                            _aio.run(broker.publish_json(int(user_id), "mlite_video", payload))
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

    bg.add_task(_run, topics, req.user_email, req.user_id, ts)
    return {"status": "started", "message": "MLite generation started.", "count": len(topics), "jobs": jobs}


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
