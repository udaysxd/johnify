# slidegen.py
import re, json
from pathlib import Path
from markdown2 import markdown
from bs4 import BeautifulSoup
import shutil
from openai import OpenAI
from typing import List, Dict, Tuple, Optional, Union
import time
import hashlib
import os
from pathlib import Path
import requests
import concurrent.futures
import asyncio

# DeepSeek client getter

def get_deepseek_client():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable not set. Slide content generation will fail.")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")

# Configuration for Pollinations AI
POLLINATIONS_BASE_URL = "https://image.pollinations.ai/prompt/"
CACHE_DIR = Path("./image_cache")
CACHE_DIR.mkdir(exist_ok=True)

# ─── helpers ────────────────────────────────────────────────────────
def markdown_to_plain_text(md: str) -> str:
    return BeautifulSoup(markdown(md), "html.parser")\
        .get_text(separator=" ", strip=True)

def fresh_dir(path: str):
    p = Path(path)
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)
    return p

def clean_markdown_text(text: str) -> str:
    """Clean and escape markdown text to prevent formatting issues."""
    if not text:
        return ""
    # Escape special markdown characters
    text = str(text)
    # First escape backslashes
    text = text.replace('\\', '\\\\')
    # Then escape other special characters
    for char in '`*_{}[]()#+-.!|':
        text = text.replace(char, f'\\{char}')
    return text

async def process_question_async(question_data: dict) -> List[str]:
    """Process a single question and generate its slides asynchronously."""
    question = clean_markdown_text(question_data.get('question', 'Question'))
    correct_answer = clean_markdown_text(question_data.get('correct_answer', 'No answer'))
    explanation = clean_markdown_text(question_data.get('explanation', 'No explanation available'))
    
    # Generate slides for this question
    return generate_concept_slides(question, correct_answer, explanation)

def extract_key_points(explanation: str) -> List[str]:
    """Extract key points from the explanation text."""
    # Split the explanation into sentences
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', explanation) if s.strip()]
    
    # Take the most important sentences (first few and last one)
    key_points = []
    if len(sentences) >= 1:
        key_points.append(sentences[0])  # First sentence is usually the main point
    if len(sentences) >= 3:
        key_points.append(sentences[1])  # Second sentence often contains important info
    if len(sentences) >= 2:
        key_points.append(sentences[-1])  # Last sentence often summarizes
    
    # Ensure we have at least 3 points
    while len(key_points) < 3:
        key_points.append("This concept is fundamental to understanding the topic.")
    
    return key_points[:3]  # Return max 3 key points

def generate_example_steps(question: str, answer: str) -> List[str]:
    """Generate example steps based on the question and answer."""
    steps = []
    
    # Step 1: Restate the question in a learning context
    steps.append(f"Let's analyze the question: {question}")
    
    # Step 2: Break down the correct answer
    steps.append(f"The correct answer is: {answer}")
    
    # Step 3: Provide context or application
    steps.append("This demonstrates an important concept in the subject area.")
    
    return steps

def generate_concept_slides(question: str, correct_answer: str, explanation: str) -> List[str]:
    """
    Generate detailed slides for a single concept with up to 5 slides.
    Uses simplified prompts for better reliability.
    """
    if not question or not correct_answer or not explanation:
        return []
        
    slides = []
    
    # Clean and format the inputs
    question = question.strip()
    correct_answer = correct_answer.strip()
    explanation = explanation.strip()
    
    # Clean and format the question for use in titles
    def clean_title(text):
        # Remove question marks and other punctuation
        text = re.sub(r'[?.,;:!]', '', text)
        # Take first 6 words or first 40 chars, whichever comes first
        words = text.split()
        short = ' '.join(words[:6])
        if len(short) > 40:
            short = short[:40].rsplit(' ', 1)[0]  # Don't cut words in middle
        return short.strip()
        
    # Generate a clean title for the concept
    concept = clean_title(question)
    
    # Generate a simple concept name for image prompts
    concept_words = [w.lower() for w in concept.split() if len(w) > 2][:3]
    concept_name = ' '.join(concept_words) if concept_words else 'learning concept'
    
    # Extract key points from the explanation
    key_points = extract_key_points(explanation)
    
    # Generate example steps
    example_steps = generate_example_steps(question, correct_answer)
    
    # Only add the first slide if we have a valid question and answer
    if question and correct_answer:
        slide1 = f"---\n"
        slide1 += f"## {concept}\n\n"
        slide1 += f"![{concept}]({get_image_url(concept_name, 800, 300)})\n\n"
        slide1 += f"**Question:** {question}\n\n"
        slide1 += f"**Correct Answer:** {correct_answer}"
        slides.append(slide1)
    
    # Slide 2: Core Concept Explanation
    if explanation:
        slide2 = f"---\n"
        slide2 += f"## {concept}: Core Concept\n\n"
        slide2 += f"![{concept} Concept]({get_image_url(f'{concept_name} concept', 800, 300)})\n\n"
        slide2 += f"{explanation}\n\n"
        
        if key_points:
            slide2 += "*Key points to remember:*\n"
            for point in key_points:
                if point.strip():
                    slide2 += f"- {point}\n"
        slides.append(slide2)
    
    # Slide 3: Example Scenario (only if we have steps)
    if example_steps and any(step.strip() for step in example_steps):
        slide3 = f"---\n"
        slide3 += f"## {concept}: Example\n\n"
        slide3 += f"![{concept} Example]({get_image_url(f'example {concept_name}', 800, 300)})\n\n"
        slide3 += "**Let's break this down:**\n\n"
        for i, step in enumerate(example_steps, 1):
            if step.strip():
                slide3 += f"{i}. {step}\n"
        slides.append(slide3)
    
    # Slide 4: Common Misconceptions (only if we have a valid question and answer)
    if question and correct_answer:
        slide4 = f"---\n"
        slide4 += f"## {concept}: Common Pitfalls\n\n"
        slide4 += f"![Common Mistakes]({get_image_url(f'mistakes {concept_name}', 800, 300)})\n\n"
        slide4 += "**Things to watch out for:**\n\n"
        
        # Only add this point if we have a question
        if '?' in question:
            question_text = question.split('?')[0].strip()
            if question_text:
                slide4 += f"- Misinterpreting the question: {question_text}?\n"
        
        # Only add this point if we have a correct answer
        if correct_answer and correct_answer.lower() != 'no correct answer found':
            slide4 += f"- Confusing {correct_answer} with similar concepts\n"
        
        # Always add this general tip
        slide4 += "- Overcomplicating the answer - sometimes the most straightforward answer is correct"
        
        slides.append(slide4)
    
    # Slide 5: Summary and Practice (only if we have key points)
    if key_points and any(point.strip() for point in key_points):
        slide5 = f"---\n"
        slide5 += f"## {concept}: Summary\n\n"
        slide5 += f"![Summary]({get_image_url(f'summary {concept_name}', 800, 300)})\n\n"
        
        # Only add the key takeaways section if we have valid points
        valid_key_points = [p for p in key_points if p.strip()]
        if valid_key_points:
            slide5 += "**Key Takeaways:**\n\n"
            for point in valid_key_points:
                slide5 += f"- {point}\n"
        
        # Add a practice prompt if we have a concept name
        if concept_name and concept_name.strip() != 'learning concept':
            first_word = concept_name.split(' ')[0]
            if first_word and len(first_word) > 2:  # Only add if we have a meaningful word
                slide5 += "\n**Try it yourself:**\n"
                slide5 += f"Think of another example where {first_word} applies in a different context."
        
        slides.append(slide5)
    
    return slides

def generate_slide_markdown(wrong_questions: List[dict]) -> List[str]:
    """
    Generate detailed learning slides for wrong questions with comprehensive explanations.
    Uses parallel processing for better performance.
    
    Args:
        wrong_questions: List of dictionaries containing wrong questions and answers
        
    Returns:
        List of markdown slide strings
    """
    try:
        if not wrong_questions:
            return []
            
        slides = []
        
        # Process questions in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            # Create a future for each question
            future_to_question = {
                executor.submit(
                    asyncio.run, 
                    process_question_async(question)
                ): question for question in wrong_questions
            }
            
            # Process completed futures as they complete
            for future in concurrent.futures.as_completed(future_to_question):
                try:
                    question_slides = future.result()
                    slides.extend(question_slides)
                except Exception as e:
                    print(f"Error processing question: {e}")
                    # Continue with other questions even if one fails
        
        return slides
        
    except Exception as e:
        print(f"Error in generate_slide_markdown: {e}")
        raise

# Update the get_image_url function to use a session for better performance
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Create a session with retry logic
session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)

def get_image_url(prompt: str, width: int = 800, height: int = 300) -> str:
    """
    Return a deterministic placeholder image URL for slide images.
    IMPORTANT: This function must NOT call Pollinations or any external API.
    """
    # Normalize prompt and derive a stable seed
    prompt_norm = re.sub(r'[^\w\s-]', ' ', (prompt or '').lower())
    words = [w for w in prompt_norm.split() if len(w) > 3][:3] or ['education', 'learning', 'concept']
    simple_prompt = (' '.join(words) + ' educational')[:50]
    cache_key = hashlib.md5(simple_prompt.encode()).hexdigest()
    # Always return a placeholder; no network call here
    return f"https://picsum.photos/seed/{cache_key}/{width}/{height}"

def save_slides_to_md(slides: List[str], output_path: str) -> None:
    """
    Save slides to a markdown file with proper Marp frontmatter and separators.
    """
    frontmatter = (
        "---\n"
        "marp: true\n"
        "theme: default\n"
        "paginate: true\n"
        "---\n"
    )

    slide_blocks = []
    for slide in slides:
        # Remove any existing YAML frontmatter and leading/trailing dashes
        slide_clean = re.sub(r'^---[\s\S]*?---\s*', '', slide.strip())
        slide_clean = slide_clean.strip('\n-')  # Remove any leading/trailing newlines or dashes
        if not slide_clean.strip():
            continue
        slide_blocks.append(slide_clean.strip())

    # Join slides with proper separators (single separator between slides)
    full_md = frontmatter + "\n---\n\n".join(slide_blocks)
    
    # Ensure we end with a newline
    if not full_md.endswith('\n'):
        full_md += '\n'

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_md)

    print(f"✅ Saved {len(slide_blocks)} slides to: {output_path}")


def remove_marp_headers_and_styles(md: str) -> str:
    """
    Fully remove Marp frontmatter, style blocks, and code blocks from a Markdown string.
    """
    # Remove Marp frontmatter blocks
    md = re.sub(r'(?m)^---\s*\n(?:.*?\n)*?^---\s*', '', md)

    # Remove style: | YAML blocks
    md = re.sub(r'(?m)^style:\s*\|(?:\n\s+.*)+', '', md, flags=re.IGNORECASE)

    # Remove HTML <style> blocks
    md = re.sub(r'<style[\s\S]*?</style>', '', md, flags=re.IGNORECASE)

    # Remove Markdown code blocks
    md = re.sub(r'```[\s\S]*?```', '', md)

    # Trim whitespace
    return md.strip()



def generate_creative_slides(topic: str, complexity_desc: str, client: OpenAI, temperature: float = 0.8) -> List[str]:
    """Let DeepSeek design the outline, slide count, and content. Return list of slide markdown strings.
    We enforce minimal formatting constraints to keep it parseable but avoid rigid structure."""
    try:
        prompt = (
            f"Design the best possible educational slide deck about: '{topic}'.\n"
            f"Audience level: {complexity_desc}.\n\n"
            "Instructions:\n"
            "- Infer the best format for this topic (e.g., recipe steps, tutorial, timeline, Q&A, checklist).\n"
            "- You decide the number of slides (6–12) based on what teaches the topic best.\n"
            "- Prefer Markdown slides: each slide begins with '## Title', then bullet points; separate slides with a line containing only --- .\n"
            "- Alternative acceptable format: 'Slide 1: Title' with lines of content; I will convert it.\n"
            "- Use clear bullet points; bold key terms where helpful.\n"
            "- Output only the slides (no extra commentary).\n\n"
            "Example (Markdown):\n"
            "## Title\n- Bullet 1\n- Bullet 2\n\n---\n\n## Next Title\n- Bullet 1\n- Bullet 2\n"
        )
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are an expert educational content creator and slide deck designer."},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            max_tokens=1600
        )
        raw = resp.choices[0].message.content or ""
        # Strip code fences if the model wrapped output
        raw = re.sub(r'^```(?:markdown|md)?\n|\n```$', '', raw.strip(), flags=re.MULTILINE)
        # First try to parse a numbered slide plan
        numbered = _parse_numbered_slide_plan(raw)
        if len(numbered) >= 4:
            return numbered[:12]
        slides = _split_markdown_slides(raw)
        # Ensure reasonable slide count
        if len(slides) < 4:
            raise ValueError("Too few slides from creative generator")
        # Light cleanup: ensure each slide starts with a title
        cleaned = []
        for s in slides:
            if not re.match(r'^##\s+', s):
                # Add a generic title if missing
                first_line = s.split('\n', 1)[0][:60].strip() or topic.title()
                s = f"## {first_line}\n" + (s if '\n' in s else '')
            cleaned.append(s.strip())
        return cleaned[:12]
    except Exception as e:
        print(f"Creative slide generation failed: {e}")
        return []

def _parse_numbered_slide_plan(text: str) -> List[str]:
    """Parse outputs like 'Slide 1: Title' followed by lines until next 'Slide N:'.
    Build markdown slides with '## Title' and bullets inferred from lines starting with '-', '*', '•', or numbered lists.
    Also extract lines like 'Text Overlay:' content into bullets.
    """
    if not text:
        return []
    t = text.replace('\r\n', '\n')
    # Remove obvious non-slide headers
    t = re.sub(r'^\s*Video Title:.*$', '', t, flags=re.MULTILINE)
    # Split by Slide N:
    chunks = re.split(r'(?m)^\s*Slide\s+\d+\s*:\s*', t)
    titles = re.findall(r'(?m)^\s*Slide\s+\d+\s*:\s*(.+)$', t)
    slides: List[str] = []
    if len(chunks) <= 1:
        return []
    # First chunk before Slide 1 header is preamble; ignore
    for i, body in enumerate(chunks[1:]):
        title = titles[i].strip() if i < len(titles) else f"Slide {i+1}"
        section = body.strip()
        # Stop at next 'Slide' header within body if parser failed to split strictly
        section = re.split(r'(?m)^\s*Slide\s+\d+\s*:', section)[0].strip()
        bullets: List[str] = []
        # Collect bullets
        for line in section.split('\n'):
            l = line.strip()
            if not l:
                continue
            # Map common prefixes to bullets
            if re.match(r'^(-|\*|•|\d+\.|\d+\))\s+', l):
                bullets.append('- ' + re.sub(r'^(-|\*|•|\d+\.|\d+\))\s+', '', l))
            elif l.lower().startswith('text overlay:'):
                content = l.split(':', 1)[1].strip()
                if content:
                    bullets.append(f'- {content}')
            elif l.lower().startswith('visual:'):
                # Keep visual as a short bullet for guidance
                content = l.split(':', 1)[1].strip()
                if content:
                    bullets.append(f'- Visual: {content}')
        # If no bullets found, derive some from sentences
        if not bullets:
            sentences = re.split(r'(?<=[.!?])\s+', section)
            for s in sentences:
                s = s.strip()
                if s:
                    bullets.append('- ' + s)
        slide_md = '## ' + title + '\n' + '\n'.join(bullets[:8])
        slides.append(slide_md)
    return slides

def _split_markdown_slides(md: str) -> List[str]:
    """Split a Marp-style markdown string into individual slide blocks.
    Accepts either '---' separators or multiple '## ' headings.
    Returns cleaned slide strings (without frontmatter)."""
    if not md:
        return []
    # Normalize newlines
    text = md.replace('\r\n', '\n').strip()
    # Remove any YAML frontmatter if present
    text = re.sub(r'(?m)^---\s*\n(?:.*?\n)*?^---\s*', '', text)
    # Prefer explicit slide separators
    parts = re.split(r'\n\s*---\s*\n', text)
    if len(parts) <= 1:
        # Fallback: split on level-2 headings starting a line
        parts = re.split(r'(?m)^##\s+', text)
        # Re-add the heading markers
        parts = [f"## {p.strip()}" for p in parts if p.strip()]
    slides = []
    for part in parts:
        s = part.strip()
        if s:
            slides.append(s)
    return slides

def generate_learn_slides(topic: str, complexity_level: int = 3, style: str = "creative") -> List[str]:
    client = get_deepseek_client()
    """
    Generate educational slides for a given topic using a fully model-led structure.
    DeepSeek decides both the format and the implicit mode; no in-code templates.
    """
    try:
        complexity_map = {1: "basic, easy-to-understand", 2: "introductory, clear", 3: "intermediate, detailed", 4: "advanced, comprehensive", 5: "expert-level, in-depth"}
        complexity_desc = complexity_map.get(complexity_level, "detailed")
        # Always use creative generation; retry at a lower temperature, then minimal fallback
        slides = generate_creative_slides(topic, complexity_desc, client, temperature=0.8)
        if slides:
            return slides
        slides = generate_creative_slides(topic, complexity_desc, client, temperature=0.6)
        if slides:
            return slides
        # Minimal fallback refined by model to avoid placeholders
        minimal = [
            f"## {topic.title()}\n- Overview\n- Why it matters\n- Where it's used",
            f"## Core Ideas\n- Key idea 1\n- Key idea 2\n- Key idea 3",
            f"## How To Learn\n- Step 1\n- Step 2\n- Step 3",
            f"## Examples\n- Example 1\n- Example 2\n- Example 3",
            f"## Summary\n- Takeaway 1\n- Takeaway 2\n- Next steps",
        ]
        refined = [_refine_slide_with_model(topic, s, client, complexity_desc) for s in minimal]
        return refined
    except Exception as e:
        print(f"Error generating slides: {str(e)}")
        # Best-effort refined minimal set on error
        try:
            complexity_desc = {1: "basic, easy-to-understand", 2: "introductory, clear", 3: "intermediate, detailed", 4: "advanced, comprehensive", 5: "expert-level, in-depth"}.get(complexity_level, "detailed")
            client = get_deepseek_client()
            minimal = [
                f"## {topic.title()}\n- Overview\n- Why it matters\n- Where it's used",
                f"## Core Ideas\n- Key idea 1\n- Key idea 2\n- Key idea 3",
                f"## Summary\n- Takeaway 1\n- Takeaway 2\n- Next steps",
            ]
            return [_refine_slide_with_model(topic, s, client, complexity_desc) for s in minimal]
        except Exception:
            return [
                f"## {topic.title()}\n- Overview\n- Why it matters\n- Where it's used",
                f"## Core Ideas\n- Key idea 1\n- Key idea 2\n- Key idea 3",
                f"## Summary\n- Takeaway 1\n- Takeaway 2\n- Next steps",
            ]

def _refine_slide_with_model(topic: str, slide_md: str, client: OpenAI, complexity_desc: str) -> str:
    """Rewrite a placeholder slide into concrete, topic-specific content while keeping the title."""
    try:
        title_match = re.match(r"^##\s*(.+)$", slide_md.strip().split('\n')[0].strip())
        title = title_match.group(1) if title_match else topic.title()
        prompt = (
            f"Topic: {topic}\n"
            f"Audience: {complexity_desc}.\n\n"
            f"Rewrite this slide by KEEPING the title and replacing placeholder bullets with concrete, specific content.\n"
            f"Title: {title}\n"
            "Bullets rules:\n"
            "- 3–6 bullets\n"
            "- No generic placeholders like 'Overview', 'Key idea 1', 'Step 1'\n"
            "- Make each bullet informative and topic-specific (rules, examples with numbers, procedures, tips).\n"
            "Output only the rewritten slide in Markdown starting with '## {Title}'."
        )
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You precisely rewrite slides to be specific and useful."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.6,
            max_tokens=400
        )
        out = resp.choices[0].message.content or ""
        out = re.sub(r'^```(?:markdown|md)?\n|\n```$', '', out.strip(), flags=re.MULTILINE)
        if out.strip().startswith('##'):
            return out.strip()
        # Fallback: reconstruct using extracted lines
        body_lines = [l.strip('- ').strip() for l in out.split('\n') if l.strip()]
        body = '\n'.join([f"- {l}" for l in body_lines[:6]])
        return f"## {title}\n{body}".strip()
    except Exception:
        return slide_md

def generate_narration(slides: list[str]) -> list[str]:
    """Generate narration for each slide using DeepSeek.
    More robust parsing: prefer delimiter-separated output, with JSON as a compatibility path.
    """
    try:
        client = get_deepseek_client()  # Get client at runtime
        MODEL = "deepseek-chat"  # Model to use for narration

        # Use a strong, simple format contract with a unique delimiter.
        DELIM = "<<<END_OF_NARRATION>>>"
        narration_prompt = (
            f"There are {len(slides)} slides below. Each starts with a heading.\n\n"
            + "\n\n".join(f"--- SLIDE {i+1} ---\n{slide}" for i, slide in enumerate(slides))
            + "\n\nWrite exactly one engaging GCSE‑level narration per slide, 60–90 words each. "
            f"Output format: write each narration as plain text, in order, separated ONLY by the line {DELIM}. "
            f"Do not return JSON, code fences, markdown, or any extra commentary. Just the narrations separated by {DELIM}. "
            "If a slide is not suitable for narration, output an empty line for that slot (still keep separators)."
        )

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a precise narrator for educational slides. Follow output format exactly."},
                {"role": "user", "content": narration_prompt}
            ],
            temperature=0.7
        )

        narration_raw = (response.choices[0].message.content or "").strip()

        # 1) Try strict JSON first (backward compatibility with previous prompt variants)
        narrations: list[str] | None = None
        try:
            parsed = json.loads(narration_raw)
            if isinstance(parsed, list):
                narrations = [str(x) if x is not None else "" for x in parsed]
        except Exception:
            # Try to extract the first JSON array from anywhere in the text
            match = re.search(r"\[\s*[\s\S]*?\s*\]", narration_raw)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, list):
                        narrations = [str(x) if x is not None else "" for x in parsed]
                except Exception:
                    narrations = None

        # 2) If not JSON, parse using the delimiter contract
        if narrations is None:
            # Strip common code fences if present
            cleaned = re.sub(r'^```[a-zA-Z]*\n|\n```$', '', narration_raw, flags=re.MULTILINE).strip()
            if DELIM in cleaned:
                parts = [p.strip() for p in cleaned.split(DELIM)]
                narrations = parts
            else:
                # 3) Fallbacks: try to parse numbered list or line-separated items
                # Try lines starting with a number or dash
                lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
                # Group lines into chunks separated by blank lines or slide markers
                chunks: list[str] = []
                buf: list[str] = []
                for ln in lines:
                    if re.match(r"^(?:\d+\.|\-)\s+", ln) or ln.lower().startswith("slide "):
                        if buf:
                            chunks.append(" ".join(buf).strip())
                            buf = []
                    buf.append(ln)
                if buf:
                    chunks.append(" ".join(buf).strip())
                narrations = chunks if chunks else []

        # Normalize and size to slides length
        if not isinstance(narrations, list):
            narrations = []
        # Trim whitespace and quotes
        narrations = [re.sub(r'^[\"\']|[\"\']$', '', (n or '')).strip() for n in narrations]

        if len(narrations) < len(slides):
            narrations += ["Please review this slide carefully."] * (len(slides) - len(narrations))
        elif len(narrations) > len(slides):
            narrations = narrations[:len(slides)]

        # Ensure non-empty strings
        narrations = [n if n else "Please review this slide carefully." for n in narrations]

        if not narrations:
            raise RuntimeError("Could not extract any narrations from model output.")
        return narrations

    except Exception as e:
        print(f"Error generating narration: {str(e)}")
        # Fallback: return a default narration for each slide
        return ["Please review this slide carefully."] * len(slides)
