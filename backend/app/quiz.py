from fastapi import APIRouter, Request
import json
from typing import List, Dict
from .slidegen import get_deepseek_client

router = APIRouter(prefix="/api/quiz", tags=["quiz"])

def mock_test():
    """Return a list of quiz questions with detailed information."""
    return [
        {
            "q": "What is the chemical symbol for water?",
            "opts": ["a) H2O", "b) CO2", "c) O2", "d) NaCl"],
            "a": "a",
            "explanation": "Water is composed of two hydrogen atoms and one oxygen atom, giving it the chemical formula H₂O."
        },
        {
            "q": "Which organelle is known as the powerhouse of the cell?",
            "opts": ["a) Nucleus", "b) Mitochondria", "c) Ribosome", "d) Chloroplast"],
            "a": "b",
            "explanation": "Mitochondria are often called the 'powerhouses' of the cell because they generate most of the cell's supply of ATP, used as a source of chemical energy."
        },
        {
            "q": "What is Newton's third law of motion?",
            "opts": [
                "a) Force equals mass times acceleration (F=ma)",
                "b) For every action, there is an equal and opposite reaction",
                "c) An object in motion stays in motion unless acted upon by an external force",
                "d) Energy cannot be created or destroyed, only transformed"
            ],
            "a": "b",
            "explanation": "Newton's third law states that for every action, there is an equal and opposite reaction. This means that any force exerted onto a body will create a force of equal magnitude but in the opposite direction on the object that exerted the first force."
        },
        {
            "q": "What is the main gas responsible for the greenhouse effect?",
            "opts": ["a) Oxygen", "b) Nitrogen", "c) Carbon dioxide", "d) Hydrogen"],
            "a": "c",
            "explanation": "While several gases contribute to the greenhouse effect, carbon dioxide (CO₂) is the primary greenhouse gas emitted through human activities such as burning fossil fuels and deforestation."
        },
        {
            "q": "Which process do plants use to make their own food?",
            "opts": ["a) Photosynthesis", "b) Respiration", "c) Transpiration", "d) Fermentation"],
            "a": "a",
            "explanation": "Photosynthesis is the process by which green plants and some other organisms use sunlight to synthesize foods with the help of chlorophyll. In this process, carbon dioxide and water are converted into glucose and oxygen."
        },
        {
            "q": "What is the unit of electric current?",
            "opts": ["a) Volt", "b) Ohm", "c) Ampere", "d) Watt"],
            "a": "c",
            "explanation": "The ampere (symbol: A) is the SI base unit of electric current, representing the flow of electric charge across a surface at the rate of one coulomb per second."
        },
        {
            "q": "What type of bond involves the sharing of electrons between atoms?",
            "opts": ["a) Ionic bond", "b) Covalent bond", "c) Metallic bond", "d) Hydrogen bond"],
            "a": "b",
            "explanation": "A covalent bond is a chemical bond that involves the sharing of electron pairs between atoms. These electron pairs are known as shared pairs or bonding pairs."
        },
        {
            "q": "What is the speed of light in a vacuum?",
            "opts": [
                "a) 3 × 10⁶ m/s (3 million meters per second)",
                "b) 3 × 10⁸ m/s (300 million meters per second)",
                "c) 3 × 10¹⁰ m/s (30 billion meters per second)",
                "d) 3 × 10⁵ m/s (300,000 meters per second)"
            ],
            "a": "b",
            "explanation": "The speed of light in a vacuum is exactly 299,792,458 meters per second (approximately 3 × 10⁸ m/s). This is a fundamental constant of nature and the maximum speed at which all conventional communication and matter can travel."
        },
        {
            "q": "Which vitamin is produced when skin is exposed to sunlight?",
            "opts": ["a) Vitamin A", "b) Vitamin C", "c) Vitamin D", "d) Vitamin K"],
            "a": "c",
            "explanation": "Vitamin D is produced in the skin through a chemical reaction that depends on sun exposure (specifically UVB radiation). This is why it's often called the 'sunshine vitamin.'"
        },
        {
            "q": "What is the formula for calculating density?",
            "opts": [
                "a) Mass / Volume",
                "b) Volume / Mass",
                "c) Mass × Volume",
                "d) Mass + Volume"
            ],
            "a": "a",
            "explanation": "Density is defined as mass per unit volume. The formula is: Density = Mass ÷ Volume. Common units include g/cm³ for solids and liquids, and g/L for gases."
        }
    ]

def _normalize_options(opts: List[str]) -> List[str]:
    """Ensure options are a list of 4 strings each prefixed with 'a) ', 'b) ', ..."""
    if not isinstance(opts, list):
        return []
    letters = ["a)", "b)", "c)", "d)"]
    out: List[str] = []
    for i in range(min(4, len(opts))):
        val = str(opts[i]).strip()
        # strip existing leading letter if present
        if len(val) >= 3 and val[:2].lower() in ["a)", "b)", "c)", "d)"]:
            val = val[3:].strip()
        out.append(f"{letters[i]} {val}")
    # pad if fewer than 4
    while len(out) < 4:
        out.append(f"{letters[len(out)]} Option {len(out)+1}")
    return out

def _validate_question(obj: Dict) -> Dict:
    """Coerce a single question into expected schema: {q, opts[4], a in [a-d], explanation}"""
    q = (obj.get("q") or obj.get("question") or "").strip()
    opts = obj.get("opts") or obj.get("options") or []
    opts = _normalize_options(opts)
    a = (obj.get("a") or obj.get("answer") or "").strip().lower()
    if a not in ["a", "b", "c", "d"]:
        a = "a"
    explanation = str(obj.get("explanation") or "").strip()
    return {"q": q, "opts": opts, "a": a, "explanation": explanation}

def generate_topic_quiz(topic: str, num_questions: int = 10) -> List[Dict]:
    """
    Use DeepSeek to generate topic-aware multiple choice questions.
    Returns validated list compatible with grading.
    """
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
        "Return ONLY a JSON array, no code fences, no extra text. Example element: {\"q\":\"...\",\"opts\":[\"a) ...\",\"b) ...\",\"c) ...\",\"d) ...\"],\"a\":\"b\",\"explanation\":\"...\"}"
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
    # try parse JSON array from content
    try:
        data = json.loads(content)
    except Exception:
        # attempt to extract first JSON array
        import re
        m = re.search(r"\[.*\]", content, re.DOTALL)
        if not m:
            raise
        data = json.loads(m.group(0))
    if not isinstance(data, list):
        raise ValueError("Model did not return a JSON array")
    normalized: List[Dict] = []
    for item in data[:num]:
        try:
            normalized.append(_validate_question(item))
        except Exception:
            continue
    # ensure we have num questions
    while len(normalized) < num:
        # backfill from mock to avoid frontend breakage
        idx = len(normalized)
        mt = mock_test()
        if idx < len(mt):
            normalized.append(mt[idx])
        else:
            break
    return normalized

@router.get("/questions")
async def get_questions():
    """Endpoint to get all quiz questions."""
    return mock_test()

@router.post("/generate")
async def generate_quiz(request: Request):
    data = await request.json()
    topic = data.get("topic", "General Knowledge")
    num_questions = int(data.get("num_questions", 10))
    # Try dynamic generation; fallback to mock on any error
    try:
        questions = generate_topic_quiz(topic, num_questions)
    except Exception as e:
        # Log-friendly message; still return a valid structure
        print(f"[quiz.generate] Fallback to mock due to error: {e}")
        questions = mock_test()[:num_questions]
    return {"topic": topic, "questions": questions}

def administer(answers, questions=None):
    """
    Grade quiz answers and identify wrong questions with detailed feedback.
    Accepts diverse answer formats: 'a'/'A', 'b) Text', numbers 1-4 or 0-3, 'option-0..3', or full option text.
    """
    if questions is None:
        questions = mock_test()
    score = 0
    wrong_indices = []
    wrong_questions = []

    def _normalize_user_key(ans, opts_list):
        try:
            s = str(ans).strip().lower()
            if not s:
                return ''
            # 'option-<n>' pattern (0-based)
            if s.startswith('option-'):
                try:
                    n = int(s.split('-', 1)[1])
                    if 0 <= n <= 3:
                        return chr(ord('a') + n)
                except Exception:
                    pass
            # Direct letter
            if s[0] in ('a','b','c','d'):
                return s[0]
            # Numeric indexes: allow '1'..'4' (1-based) and '0'..'3' (0-based)
            if s[0].isdigit():
                try:
                    n = int(s.split()[0])
                    if 1 <= n <= 4:
                        return chr(ord('a') + (n - 1))
                    if 0 <= n <= 3:
                        return chr(ord('a') + n)
                except Exception:
                    pass
            # Match against option text
            norm_opts = []
            for o in (opts_list or []):
                o_str = str(o)
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

    print(f"\n📝 Grading answers: {answers}")
    for i, answer in enumerate(answers):
        if i >= len(questions):
            print(f"⚠️ More answers ({len(answers)}) than questions ({len(questions)})")
            break
        question = questions[i]
        correct = (question.get("a") or '').strip().lower()[:1]
        opts = question.get("opts") or question.get("options") or []
        if isinstance(opts, dict):
            opts = [f"{k}) {v}" for k, v in opts.items()]
        if not isinstance(opts, list):
            print(f"[WARN] Question opts is not a list: {opts}")
            opts = []
        user_key = _normalize_user_key(answer, opts)
        print(f"  Q{i+1}: Given '{answer}', Normalized '{user_key}', Correct is '{correct}'", end="")
        if user_key == correct:
            score += 1
            print(" ✅")
        else:
            # Get the full text of the correct answer
            correct_answer_text = ""
            try:
                correct_opt_index = ord(correct) - ord('a') if correct else -1
                if 0 <= correct_opt_index < len(opts):
                    opt_val = opts[correct_opt_index]
                    correct_answer_text = opt_val[3:] if opt_val[:3].lower() in ["a) ", "b) ", "c) ", "d) "] else opt_val
            except Exception as e:
                print(f"[WARN] Failed to get correct answer text: {e}")
                correct_answer_text = ""
            # Get the user's selected answer text
            user_answer_text = ""
            if user_key:
                try:
                    user_opt_index = ord(user_key) - ord('a')
                    if 0 <= user_opt_index < len(opts):
                        opt_val = opts[user_opt_index]
                        user_answer_text = opt_val[3:] if opt_val[:3].lower() in ["a) ", "b) ", "c) ", "d) "] else opt_val
                except Exception as e:
                    print(f"[WARN] Failed to get user answer text: {e}")
                    user_answer_text = ""
            # Create a detailed question object with explanation
            wrong_question = {
                "question": question.get("q") or question.get("question", ""),
                "correct_answer": correct,
                "user_answer": user_key if user_key else "(No answer provided)",
                "options": opts,
                "explanation": question.get("explanation", ""),
                "correct_answer_text": correct_answer_text,
                "user_answer_text": user_answer_text,
                "correct_letter": correct,
                "user_letter": user_key,
                "question_number": i + 1
            }
            wrong_indices.append(i)
            wrong_questions.append(wrong_question)
            print(f" ❌ (Adding to wrong answers)")
    print(f"🎯 Score: {score}/{len(questions)}")
    print(f"❌ Wrong answers: {len(wrong_questions)}")
    return {
        "score": score,
        "total_questions": len(questions),
        "wrong_indices": wrong_indices,
        "wrong_questions": wrong_questions,
        "percentage": int((score / len(questions)) * 100) if questions else 0
    }

@router.post("/grade")
async def grade_quiz(request: Request):
    data = await request.json()
    answers = data.get("answers", [])
    questions = data.get("questions")
    # answers: list of selected answer keys (e.g., ["a", "b", ...])
    # questions: list of question dicts (optional, for dynamic quizzes)
    result = administer(answers, questions)
    return result

# Export the router
__all__ = ["router"]
