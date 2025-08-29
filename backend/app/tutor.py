from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json
import time
import re
import subprocess
from pathlib import Path
import os

import requests
from .auth import models, security

from .slidegen import get_deepseek_client, generate_slide_markdown, save_slides_to_md
from google.cloud import texttospeech
from PIL import Image, ImageDraw, ImageFont

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


def generate_topic_quiz(topic: str, num_questions: int = 10) -> Dict[str, Any]:
    """Call Deepseek once to get questions plus extras.

    Returns a dict with keys:
      - questions: List[Dict]
      - fun_facts: List[str]
      - corrected_title: str
    """
    client = get_deepseek_client()
    num = max(1, min(20, int(num_questions)))
    system = (
        "You generate a topic-based multiple-choice quiz along with extras. Return STRICT JSON ONLY with this shape: "
        "{\n  \"questions\": [ { q, opts, a, explanation } x N ],\n  \"fun_facts\": [string, ...],\n  \"corrected_title\": string\n}. "
        "Each question must have: q (string), opts (array of 4 short strings), a (one of 'a','b','c','d'), explanation (string). "
        "fun_facts should be 10 short, accurate facts about the topic. corrected_title must be <= 100 chars, typo/spell checked, concise."
    )
    user = (
        f"Create a {num}-question multiple-choice quiz on the topic: '{topic}'.\n"
        "Requirements:\n"
        "- Difficulty: GCSE/High-school level, concise and accurate.\n"
        "- opts must be exactly 4 distinct plausible choices. Prefer short options.\n"
        "- a must be the correct option's letter (a/b/c/d).\n"
        "- Provide a one-sentence explanation for the correct answer.\n"
        "Also provide exactly 10 fun_facts based on the topic and a corrected_title (<=100 chars, typo/spell-checked, concise).\n"
        "Return ONLY a single JSON object matching the specified schema. No code fences, no extra text."
    )
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.7,
        max_tokens=2000,
    )
    content = resp.choices[0].message.content.strip()

    # Parse flexible: accept dict (new) or list (legacy)
    data_obj: Dict[str, Any]
    try:
        parsed = json.loads(content)
    except Exception:
        # Legacy array fallback: extract first JSON array present
        m = re.search(r"\{.*\}|\[.*\]", content, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                parsed = []
        else:
            parsed = []

    if isinstance(parsed, dict):
        data_obj = parsed
    elif isinstance(parsed, list):
        # Legacy: wrap into object
        data_obj = {"questions": parsed}
    else:
        data_obj = {"questions": []}

    raw_questions = data_obj.get("questions") or []
    if not isinstance(raw_questions, list):
        raw_questions = []

    normalized: List[Dict] = []
    for item in raw_questions[:num]:
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

    # Fun facts normalization
    fun_facts_raw = data_obj.get("fun_facts") or []
    if not isinstance(fun_facts_raw, list):
        fun_facts_raw = []
    fun_facts: List[str] = []
    for ff in fun_facts_raw:
        try:
            s = str(ff).strip()
            if s and s not in fun_facts:
                fun_facts.append(s)
        except Exception:
            continue
    if not fun_facts:
        # minimal defaults if model omitted
        fun_facts = [
            f"Interesting fact about {topic}.",
            f"Another insight on {topic}.",
        ]
    fun_facts = fun_facts[:10]

    # Corrected title normalization
    corrected_title = data_obj.get("corrected_title") or topic or "Tutor"
    try:
        corrected_title = str(corrected_title).strip()[:100]
    except Exception:
        corrected_title = (topic or "Tutor")[:100]

    return {"questions": normalized, "fun_facts": fun_facts, "corrected_title": corrected_title}


@router.post("/generate")
async def tutor_generate_quiz(request: Request):
    data = await request.json()
    topic = data.get("topic", "General Knowledge")
    num_questions = int(data.get("num_questions", 10))
    try:
        result = generate_topic_quiz(topic, num_questions)
        # Backward-compatible shape
        questions = result.get("questions", []) if isinstance(result, dict) else (result or [])
        fun_facts = result.get("fun_facts", []) if isinstance(result, dict) else []
        corrected_title = result.get("corrected_title", topic) if isinstance(result, dict) else topic
    except Exception as e:
        print(f"[tutor.generate] Fallback to mock due to error: {e}")
        questions = mock_test()[:num_questions]
        fun_facts = [f"Interesting fact about {topic}."]
        corrected_title = topic[:100]
    return {"topic": topic, "questions": questions, "fun_facts": fun_facts, "corrected_title": corrected_title}


def administer(answers, questions=None):
    if questions is None:
        questions = mock_test()
    score = 0
    wrong_indices = []
    wrong_questions = []
    
    def _normalize_user_key(ans: Any, opts_list: list[str]) -> str:
        """Return a normalized letter 'a'..'d' for diverse user inputs.
        Accepts: 'a'/'A', 'b) Paris', '2', 1-based or 0-based numbers, or full option text.
        """
        try:
            s = str(ans).strip().lower()
            if not s:
                return ''
            # Direct letter
            if s[0] in ('a','b','c','d'):
                return s[0]
            # Numeric indexes: allow '1'..'4' (1-based) and '0'..'3' (0-based)
            if s[0].isdigit():
                n = int(s.split()[0])
                if 1 <= n <= 4:
                    return chr(ord('a') + (n - 1))
                if 0 <= n <= 3:
                    return chr(ord('a') + n)
            # Match against option text
            norm_opts = []
            for o in (opts_list or []):
                o_str = str(o)
                # strip leading 'a) ' style label
                if len(o_str) >= 3 and o_str[:3].lower() in ("a) ", "b) ", "c) ", "d) "):
                    norm_opts.append(o_str[3:].strip().lower())
                else:
                    norm_opts.append(o_str.strip().lower())
            try:
                idx = norm_opts.index(s)
                if 0 <= idx < 4:
                    return chr(ord('a') + idx)
            except ValueError:
                pass
        except Exception:
            return ''
        return ''
    for i, answer in enumerate(answers):
        if i >= len(questions):
            break
        question = questions[i]
        correct = (question.get("a") or '').strip().lower()[:1]
        # Normalize opts to a list of strings
        opts = question.get("opts") or []
        if isinstance(opts, dict):
            opts = [f"{k}) {v}" for k, v in opts.items()]
        if not isinstance(opts, list):
            opts = []

        user_answer_key = _normalize_user_key(answer, opts)
        if user_answer_key == correct:
            score += 1
        else:
            correct_answer_text = ""
            try:
                correct_opt_index = ord(correct) - ord('a') if correct else -1
                if 0 <= correct_opt_index < len(opts):
                    opt_val = opts[correct_opt_index]
                    correct_answer_text = opt_val[3:] if opt_val[:3].lower() in ["a) ", "b) ", "c) ", "d) "] else opt_val
            except Exception:
                correct_answer_text = ""
            user_answer_text = ""
            if user_answer_key:
                try:
                    user_opt_index = ord(user_answer_key) - ord('a')
                    if 0 <= user_opt_index < len(opts):
                        opt_val = opts[user_opt_index]
                        user_answer_text = opt_val[3:] if opt_val[:3].lower() in ["a) ", "b) ", "c) ", "d) "] else opt_val
                except Exception:
                    user_answer_text = ""
            wrong_question = {
                "question": question.get("q") or question.get("question", ""),
                "correct_answer": correct,
                "user_answer": user_answer_key if user_answer_key else "(No answer provided)",
                "options": opts,
                "explanation": question.get("explanation", ""),
                "correct_answer_text": correct_answer_text,
                "user_answer_text": user_answer_text,
                # explicit for UI convenience
                "correct_letter": correct,
                "user_letter": user_answer_key,
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
    user_id: Optional[int] = None
    # Optional list of tags to classify the video (genre/industry/segment/category)
    tags: Optional[List[str]] = None

# In-memory job store for tutor-only
TUTOR_VIDEO_JOBS: Dict[str, Dict[str, Any]] = {}

def _generate_topic_tags(topic: str) -> List[str]:
    """Generate exactly 7 concise tags for the given topic using DeepSeek.
    Returns a sanitized list of up to 7 strings. Empty list on failure.
    """
    try:
        client = get_deepseek_client()
    except Exception as e:
        # DeepSeek not configured
        print(f"\u26a0\ufe0f DeepSeek unavailable for tags: {e}")
        return []

    sys_msg = (
        "You are an expert taxonomy generator. "
        "Return only valid JSON: an array of exactly 7 lowercase tags (strings). "
        "Each tag must be a single word or short phrase (<= 3 words), no punctuation, no emojis."
    )
    user_msg = (
        f"Topic: {topic}\n\n"
        "Produce exactly 7 concise, descriptive tags capturing genre, industry, segment, and category.\n"
        "Output strictly as JSON array, no commentary. Example: [\"education\", \"biology\", \"k12\", \"science\", \"fundamentals\", \"tutorial\", \"intro\"]"
    )
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            temperature=0.2,
            max_tokens=200,
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ],
        )
        content = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"\u274c DeepSeek tags request failed: {e}")
        return []

    tags: List[str] = []
    # Try JSON parse first
    import json as _json
    try:
        data = _json.loads(content)
        if isinstance(data, list):
            tags = [str(x) for x in data]
    except Exception:
        # Fallback: try to parse as comma or newline separated
        raw = content.replace("[", "").replace("]", "")
        parts = [p.strip().strip('-').strip('\"\'') for p in raw.replace("\n", ",").split(",")]
        tags = [p for p in parts if p]

    # Sanitize: lowercase, trim, dedupe, max 3 words and 64 chars, first 7
    cleaned: List[str] = []
    seen = set()
    for t in tags:
        s = str(t).strip().lower()
        if not s:
            continue
        words = s.split()
        s = " ".join(words[:3])[:64]
        if s and s not in seen:
            seen.add(s)
            cleaned.append(s)
        if len(cleaned) >= 7:
            break
    return cleaned[:7]


def _tutor_generate_video_from_request(request: TutorVideoRequest, status_path: Optional[Path] = None) -> Dict[str, Any]:
    # Lazy import to avoid circular dependency; sanitize_filename lives in main.py
    from .main import sanitize_filename
    safe_topic = sanitize_filename(request.topic or 'tutor')
    # Use a normalized corrected title everywhere for consistency
    try:
        display_title = str(request.topic or 'Tutor').strip()[:100]
    except Exception:
        display_title = (request.topic or 'Tutor')[:100]
    timestamp = int(time.time())
    # Determine base generated dir (prod: /tmp/generated, dev: repo-root/generated)
    env = os.getenv("ENVIRONMENT", "development").lower()
    if env == "production":
        base_dir = Path("/tmp")
    else:
        base_dir = Path(__file__).resolve().parent.parent.parent
    generated_dir = base_dir / "generated"
    output_dir = generated_dir / "Tutor_Results" / f"{safe_topic}_{timestamp}"
    images_dir = output_dir / "images"
    audio_dir = output_dir / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(exist_ok=True)
    audio_dir.mkdir(exist_ok=True)

    # Pre-generate thumbnail early so we can use it for a title slide background
    thumb_path = output_dir / "thumbnail.jpg"
    if not thumb_path.exists():
        try:
            # Import locally to avoid circular import (main.py imports tutor module)
            from .main import generate_thumbnail_with_fallbacks
            ok = generate_thumbnail_with_fallbacks(display_title, str(thumb_path), label="tutor")
            if not ok:
                raise RuntimeError("All thumbnail fallbacks failed (tutor early)")
        except Exception as e:
            print(f"[tutor] Early thumbnail failed after fallbacks: {e}")

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

    # Helper to write status if a path is provided
    def _write_stage(payload: Dict[str, Any]):
        if not status_path:
            return
        try:
            status_path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            pass

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

    # 2) Narration (reuse helper from learn pipeline)
    from .main import generate_narration  # reuse helper
    narrations = generate_narration(slides) or ["Please review this concept carefully."] * len(slides)

    # 3) Generate slide images using the learn pipeline's Python approach
    #    Import locally to avoid circular imports
    from .main import create_simple_slide
    try:
        # 3a) Title slide using thumbnail as background with centered title text
        try:
            if thumb_path.exists():
                bg = Image.open(thumb_path).convert('RGB')
                # Resize to 1920x1080 for consistency with slides
                bg = bg.resize((1920, 1080))
                # Apply semi-transparent dark overlay for readability
                bg = bg.convert('RGBA')
                overlay = Image.new('RGBA', bg.size, (0, 0, 0, 120))  # ~47% opacity
                bg = Image.alpha_composite(bg, overlay)
                draw = ImageDraw.Draw(bg)
                title_txt = (display_title or "Tutor").strip()
                # Try a larger TrueType font; fallback to default
                font = None
                try:
                    # Attempt common fonts
                    for fp in [
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                        "C:/Windows/Fonts/arialbd.ttf",
                        "C:/Windows/Fonts/segoeuib.ttf",
                    ]:
                        if os.path.exists(fp):
                            font = ImageFont.truetype(fp, 96)
                            break
                except Exception:
                    font = None
                if font is None:
                    try:
                        font = ImageFont.load_default()
                    except Exception:
                        font = None
                # Wrap and center with horizontal padding
                pad_x = 160  # left/right padding
                max_w = max(100, 1920 - 2 * pad_x)
                words = title_txt.split()
                lines = []
                current = ""
                def _text_size(s: str):
                    try:
                        bb = draw.textbbox((0, 0), s, font=font)
                        return bb[2] - bb[0], bb[3] - bb[1]
                    except Exception:
                        try:
                            return int(draw.textlength(s, font=font)), 96  # type: ignore[attr-defined]
                        except Exception:
                            return len(s) * 14, 96
                for w in words:
                    test = (w if not current else current + " " + w)
                    tw, th = _text_size(test)
                    if tw <= max_w:
                        current = test
                    else:
                        if current:
                            lines.append(current)
                            current = w
                        else:
                            # extremely long single word: hard-cut
                            cut = w
                            while cut:
                                low, high = 1, len(cut)
                                idx = 1
                                while low <= high:
                                    mid = (low + high) // 2
                                    tw2, _ = _text_size(cut[:mid])
                                    if tw2 <= max_w:
                                        idx = mid
                                        low = mid + 1
                                    else:
                                        high = mid - 1
                                lines.append(cut[:idx])
                                cut = cut[idx:]
                            current = ""
                if current:
                    lines.append(current)
                # Compute total height for vertical centering
                line_heights = []
                max_line_w = 0
                for ln in lines:
                    tw, th = _text_size(ln)
                    max_line_w = max(max_line_w, tw)
                    line_heights.append(th)
                line_spacing = 14  # px between lines
                total_h = sum(line_heights) + max(0, (len(lines) - 1) * line_spacing)
                y = max(0, (1080 - int(total_h)) // 2)
                # Draw each line centered within padded area
                for i, ln in enumerate(lines):
                    tw, th = _text_size(ln)
                    x = pad_x + max(0, (max_w - int(tw)) // 2)
                    # soft shadow
                    draw.text((x + 3, y + 3), ln, fill=(0, 0, 0), font=font)
                    draw.text((x, y), ln, fill=(250, 250, 250), font=font)
                    y += th + line_spacing
                title_png = images_dir / "slide_000.png"
                bg.convert('RGB').save(title_png, format='PNG')
                print(f"[tutor] Title slide created: {title_png}")
        except Exception as te:
            print(f"[tutor] ⚠️ Failed to create title slide: {te}")

        # Read the markdown file content
        with open(md_file, 'r', encoding='utf-8') as f:
            markdown_content = f.read()

        # Remove YAML front matter
        markdown_content = re.sub(r'^---\n.*?\n---\n', '', markdown_content, flags=re.DOTALL)

        # Split into slides
        slide_contents = [s.strip() for s in markdown_content.split('---') if s.strip()]

        # Generate an image for each slide
        for i, slide_content in enumerate(slide_contents, 1):
            slide_content = slide_content.strip()
            if not slide_content:
                continue

            # Remove any remaining HTML comments (narration)
            slide_content = re.sub(r'<!--.*?-->', '', slide_content, flags=re.DOTALL)

            # Default title
            title = f"Slide {i}"
            content_lines = []

            # Extract title from '## '
            for line in slide_content.split('\n'):
                line = line.strip()
                if not line:
                    continue
                if line.startswith('## '):
                    if title == f"Slide {i}":
                        title = line[3:].strip()
                        continue
                content_lines.append(line)

            slide_content = '\n'.join(content_lines)

            output_path = images_dir / f"slide_{i:03d}.png"
            create_simple_slide(slide_content, str(output_path), title=title, theme="johnify")

        # Verify images were created
        png_files_check = sorted(images_dir.glob("*.png"))
        if not png_files_check:
            raise FileNotFoundError("No slide images were generated")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate slide images: {e}")

    # 4) TTS using shared helper (matches learn pipeline behavior)
    try:
        from . import tts as tts_mod
        audio_dir_path = tts_mod.narrations_to_mp3(narrations, str(audio_dir))
        # Ensure filenames align with stitching expectations: tts creates sXXX.mp3
        # The stitcher is robust (matches *.mp3); no renaming needed
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate audio: {e}")

    # Optional: Generate AI background via Hugging Face (SD 3.5 Medium)
    def _maybe_generate_ai_bg(topic: str, out_dir: Path) -> Dict[str, Any]:
        try:
            enabled = str(os.getenv("TUTOR_BG_ENABLED", "false")).lower() in ("1", "true", "yes")
            if not enabled:
                return {"attempted": False, "path": None, "error": "disabled", "status": "skipped"}
            hf_token = os.getenv("HUGGINGFACE_TOKEN")
            if not hf_token:
                print("[tutor] AI background enabled but HUGGINGFACE_TOKEN not set; skipping")
                return {"attempted": True, "path": None, "error": "no_token", "status": "skipped"}
            model_env = os.getenv("TUTOR_BG_MODEL", "stabilityai/stable-diffusion-3.5-medium")
            prompt = f"cinematic, minimalist, high-contrast background related to: {topic}. no text, letters, words, captions, logos, watermarks, signatures, signage, title"
            negative = os.getenv("TUTOR_BG_NEGATIVE", "nsfw, text, watermark, logo, low quality, blurry")

            headers = {"Authorization": f"Bearer {hf_token}"}
            payload = {
                "inputs": prompt,
                "parameters": {
                    "negative_prompt": negative,
                    "guidance_scale": 6.5,
                    "num_inference_steps": 20,
                    "width": 1280,
                    "height": 720
                }
            }

            # Output path for the generated background image
            out_path = out_dir / "bg_sd.jpg"

            # Try the requested model first, then fallbacks if 404/403
            candidate_models = [model_env,
                                "stabilityai/sdxl-turbo",
                                "stabilityai/stable-diffusion-xl-base-1.0",
                                "runwayml/stable-diffusion-v1-5"]
            # The HF Inference API may return 202 for cold-start; retry a few times per model
            for model in candidate_models:
                url = f"https://api-inference.huggingface.co/models/{model}"
                print(f"[tutor] Trying HF model: {model}")
                max_attempts = 6
                for attempt in range(1, max_attempts + 1):
                    resp = requests.post(url, headers=headers, json=payload, timeout=120)
                    ctype = resp.headers.get("content-type", "")
                    print(f"[tutor] HF response status={resp.status_code} content-type={ctype}")
                    if resp.status_code == 200 and resp.content and ctype.startswith("image"):
                        with open(out_path, "wb") as f:
                            f.write(resp.content)
                        size = out_path.stat().st_size if out_path.exists() else 0
                        print(f"[tutor] Saved AI background to {out_path} size={size} via model={model}")
                        return {"attempted": True, "path": out_path, "error": None, "status": "ok", "bytes": size, "model": model}
                    if resp.status_code == 200 and ctype.startswith("application/json"):
                        try:
                            print(f"[tutor] HF JSON: {resp.text[:300]}")
                        except Exception:
                            pass
                        # Treat JSON as failure for this attempt
                    if resp.status_code == 202:
                        sleep_s = min(10, 1 + attempt * 2)
                        print(f"[tutor] HF model loading (202). attempt={attempt}/{max_attempts}; sleeping {sleep_s}s")
                        time.sleep(sleep_s)
                        continue
                    if resp.status_code in (403, 404):
                        print(f"[tutor] HF model unavailable ({resp.status_code}) for {model}. Trying next fallback...")
                        break  # try next model
                    # Other errors: log and break to next model
                    try:
                        print(f"[tutor] HF error {resp.status_code}: {resp.text[:300]}")
                    except Exception:
                        pass
                    break
        except Exception as e:
            print(f"[tutor] Failed to generate AI background: {e}")
        return {"attempted": enabled, "path": None, "error": "exception", "status": "error"}

    ai_bg_info = _maybe_generate_ai_bg(request.topic, output_dir)
    ai_bg_path: Optional[Path] = ai_bg_info.get("path") if isinstance(ai_bg_info, dict) else None

    # 5) Choose background image for video (DISABLED for Tutor to simplify like Learn)
    png_files = sorted(images_dir.glob("*.png"))
    if not png_files:
        raise HTTPException(status_code=500, detail="No slide images found")

    # Disable overlay/background path to reduce ffmpeg complexity
    use_overlay = False
    bg_img_path: Optional[Path] = None
    # If needed in future, set use_overlay=True and restore generation code above

    # 7) Stitch to video with background + transparent slide overlay
    video_file = output_dir / "lesson_video.mp4"
    temp_dir = output_dir / "temp_segments"
    temp_dir.mkdir(exist_ok=True)

    # Collect audio files generated by tts (sXXX.mp3) and match with slides
    mp3_files = sorted(audio_dir.glob("*.mp3"))
    pair_n = min(len(png_files), len(mp3_files))
    if pair_n == 0:
        raise HTTPException(status_code=500, detail="No matching slides/audio found")

    segments = []
    # Optional: prepend a silent title segment if slide_000.png exists
    title_png = images_dir / "slide_000.png"
    if title_png.exists():
        seg0_path = temp_dir / "segment_000_title.mp4"
        try:
            _write_stage({"status": "running", "stage": "segment_0_title"})
            subprocess.run([
                "ffmpeg", "-y", "-v", "error",
                # Video input (looping image)
                "-loop", "1", "-i", str(title_png.absolute()),
                # Silent audio input to keep stream layout consistent across segments
                "-f", "lavfi", "-t", "1.5", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                # Duration and codecs
                "-t", "1.5",
                "-shortest",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-vf", "fps=30,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1",
                "-c:a", "aac",
                str(seg0_path.absolute())
            ], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=True, timeout=120)
            segments.append(seg0_path)
            print(f"[tutor] Created title segment: {seg0_path.name}")
        except Exception as e:
            print(f"[tutor] ⚠️ Failed to create title segment: {e}")
    # Exclude title slide from audio-paired segments
    png_files_no_title = [p for p in png_files if p.name != "slide_000.png"]
    pair_n = min(len(png_files_no_title), len(mp3_files))
    for i in range(pair_n):
        png = png_files_no_title[i]
        mp3 = mp3_files[i]
        seg_path = temp_dir / f"segment_{i+1:03d}.mp4"
        try:
            # Duration via ffprobe for safety; fall back to 5s
            try:
                # Write progress stage for visibility
                _write_stage({"status": "running", "stage": f"segment_{i+1}_probe", "progress": {"current": i+1, "total": pair_n}})
                result = subprocess.run([
                    "ffprobe", "-v", "error", "-show_entries",
                    "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                    str(mp3.absolute())
                ], capture_output=True, text=True, check=True, timeout=30)
                duration = float(result.stdout.strip())
            except Exception:
                duration = 5.0

            # Adaptive quality: use lower FPS for longer segments to reduce encode time on limited CPU
            default_fps = 24
            long_seg = duration > 15.0
            eff_fps = 12 if long_seg else default_fps

            # Compose: pre-render overlay with PIL if needed to mimic Learn's simple per-segment encode
            composed_png_path = None
            if use_overlay and bg_img_path is not None:
                try:
                    bg_img = Image.open(bg_img_path).convert('RGBA')
                    fg_img = Image.open(png).convert('RGBA')
                    # Resize background and foreground to target sizes
                    bg_resized = bg_img.resize((bg_w, bg_h), Image.LANCZOS)
                    fg_resized = fg_img.resize((fg_w, fg_h), Image.LANCZOS)
                    # Apply 0.8 alpha to foreground
                    r, g, b, a = fg_resized.split()
                    a = a.point(lambda x: int(x * 0.8))
                    fg_resized.putalpha(a)
                    # Composite centered
                    canvas = Image.new('RGBA', (bg_w, bg_h))
                    canvas.paste(bg_resized, (0, 0))
                    off_x = (bg_w - fg_w) // 2
                    off_y = (bg_h - fg_h) // 2
                    canvas.paste(fg_resized, (off_x, off_y), fg_resized)
                    composed_png_path = temp_dir / f"composed_{i+1:03d}.png"
                    canvas.convert('RGB').save(composed_png_path, format='PNG')
                except Exception as ce:
                    print(f"[tutor] ⚠️ PIL overlay compose failed, falling back to foreground only: {ce}")
                    composed_png_path = None
            # Progress status before segment encode
            _write_stage({"status": "running", "stage": f"segment_{i+1}_encode", "progress": {"current": i+1, "total": pair_n}})
            # Increase timeout for long segments (fixed values; no env)
            seg_timeout = 600 if long_seg else 180
            # Use composed image if available; otherwise the slide image
            png_for_ffmpeg = composed_png_path if composed_png_path else png
            # Simple per-segment encode aligned with Learn
            cmd = [
                "ffmpeg", "-y", "-v", "error",
                "-loop", "1", "-i", str(png_for_ffmpeg.absolute()),
                "-i", str(mp3.absolute()),
                "-t", str(duration),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-vf", "fps=30,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1",
                "-c:a", "aac",
                "-ar", "44100",
                "-ac", "2",
                "-shortest",
                str(seg_path.absolute())
            ]

            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=True, timeout=seg_timeout)
            segments.append(seg_path)
            try:
                print(f"[tutor] Created segment {i+1}/{pair_n}: {seg_path.name} (duration ~{duration:.2f}s)")
                # Update progress after successful segment
                _write_stage({"status": "running", "stage": f"segment_{i+1}_done", "progress": {"current": i+1, "total": pair_n}})
            except Exception:
                pass
        except subprocess.TimeoutExpired as te:
            print(f"[tutor] ⚠️ Timeout creating segment {i+1}: {te}")
            _write_stage({"status": "running", "stage": f"segment_{i+1}_timeout", "progress": {"current": i+1, "total": pair_n}})
            continue
        except Exception as e:
            print(f"[tutor] ⚠️ Failed to create segment {i+1}: {e}")
            _write_stage({"status": "running", "stage": f"segment_{i+1}_error", "progress": {"current": i+1, "total": pair_n}, "error": str(e)})
            continue

    if not segments:
        raise HTTPException(status_code=500, detail="No segments were created")

    # Concat segments
    concat_file = temp_dir / "concat.txt"
    # Use LF newlines for ffmpeg. Write in the simple concat list format with single quotes.
    # This avoids Windows interpreting double quotes as literal characters.
    with open(concat_file, 'w', encoding='utf-8', newline='\n') as f:
        for seg in segments:
            p = seg.resolve().as_posix()
            # Escape single quotes if present (rare on Windows paths)
            p = p.replace("'", "'\\''")
            f.write(f"file '{p}'\n")

    # Quick sanity check for referenced files and log concat file contents
    try:
        missing_or_empty = []
        for seg in segments:
            try:
                if (not seg.exists()) or (seg.stat().st_size == 0):
                    missing_or_empty.append(str(seg))
            except Exception:
                missing_or_empty.append(str(seg))
        print(f"[tutor] Concat file written at: {concat_file}")
        try:
            preview = concat_file.read_text(encoding='utf-8')
            print(f"[tutor] concat.txt contents (first 20 lines):\n" + "\n".join(preview.splitlines()[:20]))
        except Exception as _e:
            print(f"[tutor] Unable to read concat.txt for preview: {_e}")
        if missing_or_empty:
            msg = f"Some segments are missing or empty: {missing_or_empty[:5]}" + (" (and more)" if len(missing_or_empty) > 5 else "")
            print(f"[tutor] WARNING: {msg}")
            _write_stage({"status": "running", "stage": "concat_validation", "warning": msg})
    except Exception as _e:
        print(f"[tutor] Concat validation failed: {_e}")

    # Mark concat stage
    _write_stage({"status": "running", "stage": "concat"})
    try:
        res1 = subprocess.run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file.absolute()),
            "-c", "copy",
            str(video_file.absolute())
        ], capture_output=True, text=True, check=True, timeout=600)
        if res1.stderr:
            print(f"[tutor] ffmpeg concat (copy) stderr:\n{res1.stderr.strip()}")
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip() if hasattr(e, 'stderr') else str(e)
        print(f"[tutor] ffmpeg concat (copy) failed. stderr:\n{err}")
        _write_stage({"status": "running", "stage": "concat_copy_error", "error": err})
        # Retry with re-encode to handle any slight codec/parameter mismatches across segments
        _write_stage({"status": "running", "stage": "concat_retry_encode"})
        try:
            res2 = subprocess.run([
                "ffmpeg", "-y", "-v", "error",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_file.absolute()),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(video_file.absolute())
            ], capture_output=True, text=True, check=True, timeout=1800)
            if res2.stderr:
                print(f"[tutor] ffmpeg concat (reencode) stderr:\n{res2.stderr.strip()}")
        except subprocess.CalledProcessError as e2:
            err2 = (e2.stderr or "").strip() if hasattr(e2, 'stderr') else str(e2)
            print(f"[tutor] ffmpeg concat (reencode) failed. stderr:\n{err2}")
            _write_stage({"status": "error", "stage": "concat_retry_encode", "error": err2})
            raise
    try:
        size_mb = video_file.stat().st_size / (1024*1024) if video_file.exists() else 0
        print(f"[tutor] Concatenated {len(segments)} segments into {video_file} ({size_mb:.2f} MB)")
    except Exception:
        pass

    # Generate thumbnail.jpg similar to Learn pipeline (Pollinations first, then PIL fallback)
    thumb_path = output_dir / "thumbnail.jpg"
    if not thumb_path.exists():
        try:
            import urllib.parse
            prompt = f"clean minimal educational thumbnail for: {display_title} (tutor), without any text, letters, words, captions, logos, watermarks, signatures, signage, title"
            encoded = urllib.parse.quote(str(prompt)[:200])
            url = f"https://image.pollinations.ai/prompt/{encoded}"
            print(f"[tutor] Generating thumbnail via Pollinations: {url}")
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            with open(thumb_path, 'wb') as f:
                f.write(resp.content)
            if thumb_path.stat().st_size < 1024:
                raise RuntimeError("Thumbnail too small; treating as failure")
        except Exception as e:
            print(f"[tutor] Pollinations thumbnail failed: {e}. Using simple PIL fallback.")
            try:
                img = Image.new('RGB', (1280, 720), color=(20, 32, 48))
                draw = ImageDraw.Draw(img)
                title = (display_title or "Tutor").strip()[:60]
                font = ImageFont.load_default()
                try:
                    bbox = draw.textbbox((0, 0), title, font=font)
                    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                except Exception:
                    try:
                        tw = draw.textlength(title, font=font)  # type: ignore[attr-defined]
                        th = 56
                    except Exception:
                        tw, th = 400, 56
                x = max(0, (1280 - int(tw)) // 2)
                y = max(0, (720 - int(th)) // 2)
                draw.text((x, y), title, fill=(235, 245, 255), font=font)
                img.save(thumb_path, format='JPEG', quality=85)
                print(f"[tutor] Fallback thumbnail saved: {thumb_path}")
            except Exception as e2:
                print(f"[tutor] ⚠️ Failed to save fallback thumbnail: {e2}")

    # 7) Optionally upload to GCS (production) and compute public URLs
    #    Mirror learn pipeline behavior: prefer GCS HTTPS in production
    rel = str(video_file).replace('\\', '/').split('generated/', 1)[-1]
    video_filename = Path(rel).name
    gcs_used = False
    gcs_video_https = ""
    gcs_thumb_https = ""
    # Mark upload stage
    _write_stage({"status": "running", "stage": "upload"})
    try:
        from . import gcs_utils
        ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
        IS_PRODUCTION = ENVIRONMENT == "production"
        if IS_PRODUCTION:
            try:
                # e.g., tutor/tutor_<safe_topic>_<timestamp>/lesson_video.mp4
                # Keep a separate namespace from learn/
                safe_topic = Path(rel).parts[1] if len(Path(rel).parts) > 1 else "tutor"
                # Use the output directory name as the folder under tutor/
                gcs_dir = f"tutor/{Path(rel).parent.name}"
                up_video = gcs_utils.maybe_upload_and_url(
                    str(video_file),
                    parts=[gcs_dir, video_filename],
                )
                if isinstance(up_video, dict):
                    gcs_video_https = up_video.get("https_url", "")
                thumb_local = output_dir / "thumbnail.jpg"
                if thumb_local.exists():
                    up_thumb = gcs_utils.maybe_upload_and_url(
                        str(thumb_local),
                        parts=[gcs_dir, "thumbnail.jpg"],
                    )
                    if isinstance(up_thumb, dict):
                        gcs_thumb_https = up_thumb.get("https_url", "")
                gcs_used = bool(gcs_video_https)
                if gcs_used:
                    print(f"[tutor] Uploaded to GCS under {gcs_dir}")
            except Exception as e:
                print(f"⚠️ GCS upload failed (tutor): {e}")
    except Exception:
        # gcs_utils import not available; skip upload
        pass

    # Prefer GCS URL if available; otherwise fall back to backend-served path
    video_url = gcs_video_https if (gcs_used and gcs_video_https) else f"/videos/{rel}"
    thumb_url = (
        gcs_thumb_https if (gcs_used and gcs_thumb_https) else f"/videos/{rel.rsplit('/', 1)[0]}/thumbnail.jpg"
    ) if (output_dir / "thumbnail.jpg").exists() else None
    try:
        from .database import SessionLocal
        from .auth.models import User, UserPost
        from sqlalchemy.exc import IntegrityError, SQLAlchemyError
        from datetime import datetime

        db = None
        try:
            db = SessionLocal()
            user = None
            # Prefer explicit user_id if provided
            if getattr(request, "user_id", None):
                user = db.query(User).filter(User.user_id == request.user_id).first()
            # Fallback to email lookup
            if not user and request.user_email:
                user = db.query(User).filter(User.user_email == request.user_email).first()
            if user:
                # Generate 7 tags via DeepSeek based on the display title/topic
                req_tags = _generate_topic_tags(display_title or request.topic)
                # Fallback: lightly sanitize any client-provided tags if DeepSeek failed
                if not req_tags:
                    try:
                        if isinstance(getattr(request, "tags", None), list):
                            tmp = []
                            for t in request.tags:
                                try:
                                    s = str(t).strip()
                                    if s:
                                        tmp.append(s[:64])
                                except Exception:
                                    continue
                            seen = set()
                            req_tags = []
                            for s in tmp:
                                k = s.lower()
                                if k not in seen:
                                    seen.add(k)
                                    req_tags.append(s)
                            req_tags = req_tags[:7]
                    except Exception:
                        req_tags = []

                # If we uploaded to GCS in production, prefer storing the HTTPS URL in post_path
                # so that videos service can short-circuit to public URLs without filesystem access.
                # Otherwise, store a generated/ relative path for local discovery.
                db_post_path = gcs_video_https if (gcs_used and gcs_video_https) else f"generated/{rel}"
                post = UserPost(
                    user_id=user.user_id,
                    post_path=db_post_path,
                    post_topic=display_title,
                    created_on=datetime.utcnow(),
                    type='tutortemp',
                    public=True,
                    tags=req_tags or []
                )
                db.add(post)
                try:
                    db.commit()
                    db.refresh(post)
                    print(f"✅ Saved tutor post to user_posts id={post.post_id} type='tutortemp' post_path={post.post_path}")
                except IntegrityError as ie:
                    db.rollback()
                    print(f"❌ Integrity error saving tutor post: {ie}")
            else:
                print("⚠️ No matching user for provided user_id/email; skipping user_posts insert for tutor video")
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

    # Return final URLs (prefer GCS in production when available)
    return {
        "status": "done",
        "videos": [{"url": video_url}],
        "video_url": video_url,
        "thumbnail_url": thumb_url,
        "message": "Tutor video generated successfully",
        # Debug info for AI background
        # AI background fields maintained for backward-compat, though generation method changed
        "ai_bg_attempted": bool(ai_bg_info.get("attempted", False)) if isinstance(ai_bg_info, dict) else False,
        "ai_bg_used": False,
        "ai_bg_error": ai_bg_info.get("error") if isinstance(ai_bg_info, dict) else None,
        "ai_bg_path": str(ai_bg_path) if ai_bg_path else None,
        "bg_chosen": None,
    }


@router.post("/generate-video")
async def tutor_generate_video_endpoint(
    request: TutorVideoRequest,
    current_user: models.User = Depends(security.get_current_active_user),
):
    # Ensure we tag the job with the authenticated user's email for DB insertion
    try:
        if not request.user_email and getattr(current_user, "user_email", None):
            request.user_email = current_user.user_email
        if not request.user_id and getattr(current_user, "user_id", None):
            request.user_id = current_user.user_id
    except Exception:
        pass
    return _tutor_generate_video_from_request(request)


@router.post("/generate-video/start")
async def tutor_generate_video_start(
    request: TutorVideoRequest,
    current_user: models.User = Depends(security.get_current_active_user),
):
    import uuid, asyncio
    job_id = uuid.uuid4().hex
    TUTOR_VIDEO_JOBS[job_id] = {"status": "running"}

    # Persist status to disk. In Cloud Run only /tmp is writable; use that in production
    env = os.getenv("ENVIRONMENT", "development").lower()
    async_dir = Path("/tmp/async") if env == "production" else Path("generated/async")
    try:
        async_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    status_path = async_dir / f"{job_id}.json"
    try:
        status_path.write_text(json.dumps({"status": "running", "stage": "queued"}), encoding="utf-8")
    except Exception:
        # Non-fatal if writing status file fails
        pass

    async def worker():
        try:
            # Attach current user email if missing
            try:
                if not request.user_email and getattr(current_user, "user_email", None):
                    request.user_email = current_user.user_email
                if not request.user_id and getattr(current_user, "user_id", None):
                    request.user_id = current_user.user_id
            except Exception:
                pass
            # Mark stage before heavy work
            try:
                status_path.write_text(json.dumps({"status": "running", "stage": "starting"}), encoding="utf-8")
            except Exception:
                pass
            # Run the heavy synchronous pipeline in a background thread to avoid blocking the event loop
            result = await asyncio.to_thread(_tutor_generate_video_from_request, request, status_path)
            final = {"status": "done", **result}
            TUTOR_VIDEO_JOBS[job_id] = final
            try:
                status_path.write_text(json.dumps(final), encoding="utf-8")
                print(f"[tutor] Job {job_id} status=done written to {status_path}")
            except Exception:
                pass
        except Exception as e:
            err = {"status": "error", "error": str(e)}
            TUTOR_VIDEO_JOBS[job_id] = err
            try:
                status_path.write_text(json.dumps(err), encoding="utf-8")
                print(f"[tutor] Job {job_id} status=error written to {status_path}: {e}")
            except Exception:
                pass

    asyncio.create_task(worker())
    return {"job_id": job_id, "status": "queued"}


@router.get("/generate-video/status/{job_id}")
async def tutor_generate_video_status(job_id: str):
    job = TUTOR_VIDEO_JOBS.get(job_id)
    if job:
        return job
    # Fallback to disk status (cross-instance best-effort). Use prod/dev path logic
    try:
        env = os.getenv("ENVIRONMENT", "development").lower()
        base = Path("/tmp/async") if env == "production" else Path("generated/async")
        status_path = base / f"{job_id}.json"
        if status_path.exists():
            with open(status_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Also repopulate in-memory cache for subsequent reads
                if isinstance(data, dict):
                    TUTOR_VIDEO_JOBS[job_id] = data
                return data
    except Exception:
        pass
    return {"status": "unknown", "error": "Invalid job_id"}
