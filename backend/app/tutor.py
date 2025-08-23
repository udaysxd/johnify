from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json
import time
import re
import subprocess
from pathlib import Path

from .slidegen import get_deepseek_client, generate_slide_markdown, save_slides_to_md
from .pptx_gen import export_slides_to_png_with_marp
from google.cloud import texttospeech

router = APIRouter(prefix="/api/tutor", tags=["tutor"]) 

# ---------- Tutor quiz generation/grading (independent copy) ----------

def _normalize_options(opts: List[str]) -> List[str]:
    if not isinstance(opts, list):
        return []
    letters = ["a)", "b)", "c)", "d)"]
    out: List[str] = []
    for i in range(min(4, len(opts))):
        val = str(opts[i]).strip()
        if len(val) >= 3 and val[:2].lower() in ["a)", "b)", "c)", "d)"]:
            val = val[3:].strip()
        out.append(f"{letters[i]} {val}")
    while len(out) < 4:
        out.append(f"{letters[len(out)]} Option {len(out)+1}")
    return out

def _validate_question(obj: Dict) -> Dict:
    q = (obj.get("q") or obj.get("question") or "").strip()
    opts = obj.get("opts") or obj.get("options") or []
    opts = _normalize_options(opts)
    a = (obj.get("a") or obj.get("answer") or "").strip().lower()
    if a not in ["a", "b", "c", "d"]:
        a = "a"
    explanation = str(obj.get("explanation") or "").strip()
    return {"q": q, "opts": opts, "a": a, "explanation": explanation}


def mock_test() -> List[Dict]:
    # Short 3-question default for tutor
    return [
        {"q":"What is 2+2?","opts":["a) 3","b) 4","c) 5","d) 6"],"a":"b","explanation":"2+2=4."},
        {"q":"Capital of France?","opts":["a) London","b) Paris","c) Berlin","d) Madrid"],"a":"b","explanation":"Paris."},
        {"q":"Sun rises in?","opts":["a) North","b) South","c) East","d) West"],"a":"c","explanation":"East."},
    ]


def generate_topic_quiz(topic: str, num_questions: int = 10) -> List[Dict]:
    client = get_deepseek_client()
    num = max(1, min(20, int(num_questions)))
    system = (
        "You generate multiple-choice quizzes. Return STRICT JSON ONLY. "
        "Each question must have: q (string), opts (array of 4 strings), a (one of 'a','b','c','d'), explanation (string)."
    )
    user = (
        f"Create a {num}-question multiple-choice quiz on the topic: '{topic}'.\n"
        "Requirements:\n"
        "- Difficulty: GCSE/High-school level, concise and accurate.\n"
        "- opts must be exactly 4 distinct plausible choices. Prefer short options.\n"
        "- a must be the correct option's letter (a/b/c/d).\n"
        "- Provide a one-sentence explanation for the correct answer.\n"
        "Return ONLY a JSON array, no code fences, no extra text."
    )
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.7,
        max_tokens=1500,
    )
    content = resp.choices[0].message.content.strip()
    try:
        data = json.loads(content)
    except Exception:
        import re
        m = re.search(r"\[.*\]", content, re.DOTALL)
        if not m:
            data = []
        else:
            data = json.loads(m.group(0))
    if not isinstance(data, list):
        data = []
    normalized: List[Dict] = []
    for item in data[:num]:
        try:
            normalized.append(_validate_question(item))
        except Exception:
            continue
    while len(normalized) < num:
        mt = mock_test()
        idx = len(normalized)
        if idx < len(mt):
            normalized.append(mt[idx])
        else:
            break
    return normalized


@router.post("/generate")
async def tutor_generate_quiz(request: Request):
    data = await request.json()
    topic = data.get("topic", "General Knowledge")
    num_questions = int(data.get("num_questions", 10))
    try:
        questions = generate_topic_quiz(topic, num_questions)
    except Exception as e:
        print(f"[tutor.generate] Fallback to mock due to error: {e}")
        questions = mock_test()[:num_questions]
    return {"topic": topic, "questions": questions}


def administer(answers, questions=None):
    if questions is None:
        questions = mock_test()
    score = 0
    wrong_indices = []
    wrong_questions = []
    for i, answer in enumerate(answers):
        if i >= len(questions):
            break
        question = questions[i]
        correct = question.get("a")
        user_answer = answer.strip().lower() if answer else ""
        if user_answer == (correct.lower() if correct else ""):
            score += 1
        else:
            opts = question.get("opts") or []
            if isinstance(opts, dict):
                opts = [f"{k}) {v}" for k, v in opts.items()]
            if not isinstance(opts, list):
                opts = []
            correct_answer_text = ""
            try:
                correct_opt_index = ord(correct.lower()) - ord('a') if correct else -1
                if 0 <= correct_opt_index < len(opts):
                    opt_val = opts[correct_opt_index]
                    correct_answer_text = opt_val[3:] if opt_val[:3].lower() in ["a) ", "b) ", "c) ", "d) "] else opt_val
            except Exception:
                correct_answer_text = ""
            user_answer_text = ""
            if user_answer:
                try:
                    user_opt_index = ord(user_answer[0].lower()) - ord('a')
                    if 0 <= user_opt_index < len(opts):
                        opt_val = opts[user_opt_index]
                        user_answer_text = opt_val[3:] if opt_val[:3].lower() in ["a) ", "b) ", "c) ", "d) "] else opt_val
                except Exception:
                    user_answer_text = ""
            wrong_question = {
                "question": question.get("q") or question.get("question", ""),
                "correct_answer": correct,
                "user_answer": user_answer if user_answer else "(No answer provided)",
                "options": opts,
                "explanation": question.get("explanation", ""),
                "correct_answer_text": correct_answer_text,
                "user_answer_text": user_answer_text,
                "question_number": i + 1
            }
            wrong_indices.append(i)
            wrong_questions.append(wrong_question)
    return {
        "score": score,
        "total_questions": len(questions),
        "wrong_indices": wrong_indices,
        "wrong_questions": wrong_questions,
        "percentage": int((score / len(questions)) * 100) if questions else 0
    }


@router.post("/grade")
async def tutor_grade_quiz(request: Request):
    data = await request.json()
    answers = data.get("answers", [])
    questions = data.get("questions")
    result = administer(answers, questions)
    return result

# ---------- Tutor video pipeline (independent) ----------

class TutorVideoRequest(BaseModel):
    topic: str
    questions: List[Dict[str, Any]]
    answers: Dict[str, str]
    user_email: Optional[str] = None

# In-memory job store for tutor-only
TUTOR_VIDEO_JOBS: Dict[str, Dict[str, Any]] = {}


def _tutor_generate_video_from_request(request: TutorVideoRequest) -> Dict[str, Any]:
    # Lazy import to avoid circular dependency; sanitize_filename lives in main.py
    from .main import sanitize_filename
    safe_topic = sanitize_filename(request.topic or 'tutor')
    timestamp = int(time.time())
    output_dir = Path(f"generated/Tutor_Results/{safe_topic}_{timestamp}")
    images_dir = output_dir / "images"
    audio_dir = output_dir / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(exist_ok=True)
    audio_dir.mkdir(exist_ok=True)

    # Prepare wrong questions from provided questions/answers
    wrong_questions: List[Dict[str, Any]] = []
    for idx, question in enumerate(request.questions):
        opts = question.get('opts')
        if isinstance(opts, dict):
            opts_list = [f"{k}) {v}" for k, v in opts.items()]
        elif isinstance(opts, list):
            opts_list = opts
        else:
            opts_list = []
        q_idx = str(idx)
        user_ans = request.answers.get(q_idx)
        correct_key = str(question.get('a', '')).lower()
        if not user_ans:
            continue
        # normalize
        user_key = str(user_ans)[0].lower()
        if user_key != (correct_key[0] if correct_key else ''):
            wrong_questions.append({
                'q': question.get('q', 'No question'),
                'opts': opts_list,
                'a': correct_key or 'a',
                'explanation': question.get('explanation', ''),
            })

    if not wrong_questions:
        return {"status": "completed", "message": "All answers correct", "videos": [], "video_url": ""}

    # 1) Slides
    slide_inputs = []
    for q in wrong_questions:
        slide_inputs.append({
            "question": q.get("q", ""),
            "correct_answer": q.get("a", ""),
            "explanation": q.get("explanation", ""),
            "options": q.get("opts", []),
        })
    slides = generate_slide_markdown(slide_inputs)
    # Tutor-specific: strip image markdown lines to avoid random images in slides
    filtered_slides: List[str] = []
    for slide in slides:
        lines = slide.split('\n')
        lines = [ln for ln in lines if not re.match(r'^!\[.*?\]\(.*?\)\s*$', ln.strip())]
        filtered_slides.append('\n'.join(lines))
    slides = filtered_slides
    md_file = output_dir / "slides.md"
    save_slides_to_md(slides, str(md_file))

    # 2) Narration
    from .main import generate_narration  # reuse helper
    narrations = generate_narration(slides) or ["Please review this concept carefully."] * len(slides)

    # 3) TTS
    tts_client = texttospeech.TextToSpeechClient()
    for idx, narration in enumerate(narrations, 1):
        speech = tts_client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=narration),
            voice=texttospeech.VoiceSelectionParams(language_code="en-GB", name="en-GB-Standard-A"),
            audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
        )
        audio_file = audio_dir / f"slide_{idx:03d}.mp3"
        with open(audio_file, "wb") as out:
            out.write(speech.audio_content)

    # 4) Slide PNGs via Marp
    export_slides_to_png_with_marp(md_file, images_dir)

    # 5) Stitch to video
    png_files = sorted(images_dir.glob("*.png"))
    if not png_files:
        raise HTTPException(status_code=500, detail="No slide images found")

    temp_dir = output_dir / "temp_segments"
    temp_dir.mkdir(exist_ok=True)

    # Use the first slide PNG as a background thumbnail for subtle motion
    bg_thumb = png_files[0]

    # Create segments
    segments = []
    for i, png in enumerate(png_files, 1):
        mp3 = audio_dir / f"slide_{i:03d}.mp3"
        # duration via ffprobe
        try:
            result = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                str(mp3.absolute())
            ], capture_output=True, text=True, check=True)
            duration = float(result.stdout.strip())
        except Exception:
            duration = 5.0
        seg_path = temp_dir / f"segment_{i:03d}.mp4"
        frames = max(1, int(duration * 30))
        # Build a GPU-free animation pipeline:
        # - Background: first slide (thumbnail), slow zoom + tiny rotate + vignette, slight blur, animated noise (particle-like)
        # - Foreground: current slide scaled to 1280x720 with slight transparency
        # - Overlay FG on BG, map audio, encode
        filter_complex = (
            f"[0:v]scale=1280:720,zoompan=z='min(1.08,zoom+0.00015)':d={frames}:s=1280x720,fps=30,"
            f"rotate=0.003*t:c=black@0,boxblur=2:1,vignette=PI/6:0.3[bg];"
            f"[1:v]scale=1280:720,format=rgba,colorchannelmixer=aa=0.92[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,noise=alls=6:allf=t[outv]"
        )
        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(bg_thumb.absolute()),
            "-loop", "1", "-i", str(png.absolute()),
            "-i", str(mp3.absolute()),
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "2:a",
            "-t", str(duration),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            str(seg_path.absolute())
        ], check=True)
        segments.append(seg_path)

    # Concat segments
    concat_file = temp_dir / "concat.txt"
    with open(concat_file, 'w') as f:
        for seg in segments:
            f.write(f"file '{seg.absolute()}'\n")

    video_file = output_dir / "lesson_video.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file.absolute()),
        "-c", "copy",
        str(video_file.absolute())
    ], check=True)

    # 6) Generate thumbnail for UI cards
    thumb_path = output_dir / "thumbnail.jpg"
    try:
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(video_file.absolute()),
            "-ss", "00:00:01.000",
            "-vframes", "1",
            str(thumb_path.absolute())
        ], check=True)
    except Exception as e:
        print(f"⚠️ Failed to generate thumbnail for tutor video: {e}")

    # 7) Record in user_posts (type='tutortemp')
    rel = str(video_file).replace('\\', '/').split('generated/', 1)[-1]
    video_url = f"/videos/{rel}"
    try:
        from .database import SessionLocal
        from .auth.models import User, UserPost
        from sqlalchemy.exc import IntegrityError, SQLAlchemyError
        from datetime import datetime

        db = None
        try:
            db = SessionLocal()
            user = None
            if request.user_email:
                user = db.query(User).filter(User.user_email == request.user_email).first()
            if not user:
                # Fallback to first user for testing environments
                users = db.query(User).all()
                if users:
                    user = users[0]
            if user:
                post = UserPost(
                    user_id=user.user_id,
                    # Store a resolvable generated/ path for videos service to locate files
                    post_path=f"generated/{rel}",
                    post_topic=request.topic,
                    created_on=datetime.utcnow(),
                    type='tutortemp'
                )
                db.add(post)
                try:
                    db.commit()
                    db.refresh(post)
                    print(f"✅ Saved tutor post to user_posts id={post.post_id} type='tutortemp'")
                except IntegrityError as ie:
                    db.rollback()
                    print(f"❌ Integrity error saving tutor post: {ie}")
            else:
                print("⚠️ No user found; skipping user_posts insert for tutor video")
        except SQLAlchemyError as sae:
            if db:
                db.rollback()
            print(f"❌ DB error (tutor): {sae}")
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass
    except Exception as e:
        print(f"⚠️ Unexpected error inserting tutor post: {e}")

    # Return local served URL
    return {
        "status": "done",
        "videos": [{"url": video_url}],
        "video_url": video_url,
        "message": "Tutor video generated successfully"
    }


@router.post("/generate-video")
async def tutor_generate_video_endpoint(request: TutorVideoRequest):
    return _tutor_generate_video_from_request(request)


@router.post("/generate-video/start")
async def tutor_generate_video_start(request: TutorVideoRequest):
    import uuid, asyncio
    job_id = uuid.uuid4().hex
    TUTOR_VIDEO_JOBS[job_id] = {"status": "running"}

    async def worker():
        try:
            result = _tutor_generate_video_from_request(request)
            TUTOR_VIDEO_JOBS[job_id] = {"status": "done", **result}
        except Exception as e:
            TUTOR_VIDEO_JOBS[job_id] = {"status": "error", "error": str(e)}

    asyncio.create_task(worker())
    return {"job_id": job_id, "status": "queued"}


@router.get("/generate-video/status/{job_id}")
async def tutor_generate_video_status(job_id: str):
    job = TUTOR_VIDEO_JOBS.get(job_id)
    if not job:
        return {"status": "unknown", "error": "Invalid job_id"}
    return job
