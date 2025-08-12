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
    Generate an image using Pollinations AI with caching.
    Returns a URL to the generated image or a placeholder if generation fails.
    """
    # Simplify and clean the prompt
    prompt = prompt.lower()
    prompt = re.sub(r'[^\w\s-]', ' ', prompt)  # Remove special chars
    words = [w for w in prompt.split() if len(w) > 3][:3]  # Get up to 3 meaningful words
    if not words:
        words = ['education', 'learning', 'concept']
    
    # Create a simple, reliable prompt
    simple_prompt = ' '.join(words) + ' educational'
    simple_prompt = simple_prompt[:50]  # Keep it short and sweet
    
    # Create a unique cache key
    cache_key = hashlib.md5(simple_prompt.encode()).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}.jpg"
    
    # Return cached image if it exists and is not empty
    if cache_file.exists() and cache_file.stat().st_size > 0:
        return f"https://picsum.photos/seed/{cache_key}/{width}/{height}"
    
    try:
        # Try to generate a new image (using the session for better performance)
        encoded_prompt = requests.utils.quote(simple_prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        
        response = session.get(image_url, timeout=10)  # Using the session here
        response.raise_for_status()
        
        # Save the image to cache
        with open(cache_file, 'wb') as f:
            f.write(response.content)
            
        return f"https://picsum.photos/seed/{cache_key}/{width}/{height}"
        
    except Exception as e:
        print(f"Error generating image: {e}")
        # Fallback to a placeholder with a unique URL based on the prompt
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



def generate_learn_slides(topic: str, complexity_level: int = 3) -> List[str]:
    client = get_deepseek_client()
    """
    Generate educational slides for a given topic.
    
    Args:
        topic: The topic to generate slides about
        complexity_level: Integer from 1 (basic) to 5 (advanced)
        
    Returns:
        List of slide markdown strings
    """
    try:
        # Define complexity-based parameters
        complexity_map = {
            1: "basic, easy-to-understand",
            2: "introductory, clear",
            3: "intermediate, detailed",
            4: "advanced, comprehensive",
            5: "expert-level, in-depth"
        }
        complexity_desc = complexity_map.get(complexity_level, "detailed")
        
        # Generate slide content using DeepSeek
        def generate_slide_content(prompt: str, min_bullets: int = 2) -> str:
            """Helper function to generate content for a single slide."""
            try:
                # Add explicit formatting instructions
                prompt = f"""{prompt}
                
                FORMATTING RULES:
                - Each main point must start with a '- ' (dash and space)
                - Include 2-4 bullet points per slide
                - Each bullet point should be 1-2 short sentences
                - Use **bold** for emphasis on key terms
                - Keep language clear and concise
                - Never use placeholders like 'key concept 1'
                - Ensure all bullet points are properly formatted with '- ' at the start
                
                Example of good formatting:
                - First main point with a brief explanation
                - Second point that expands on the topic
                - Final point that summarizes or provides context
                
                Now generate content following these rules:
                """
                
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": f"You are an expert educational content creator. Generate clear, engaging content for educational slides about {topic} at a {complexity_desc} level."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=500
                )
                
                content = response.choices[0].message.content.strip()
                
                # Ensure we have proper bullet points
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                bullet_points = [line for line in lines if line.startswith('-')]
                
                # If we don't have enough bullet points, generate more
                if len(bullet_points) < min_bullets:
                    additional_prompt = f"""
                    The previous response didn't have enough bullet points. 
                    Please provide {min_bullets} more bullet points about: {topic}
                    
                    Format each point with '- ' at the start.
                    """
                    additional_response = client.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": f"You are an expert educational content creator."},
                            {"role": "user", "content": additional_prompt}
                        ],
                        temperature=0.7,
                        max_tokens=300
                    )
                    additional_content = additional_response.choices[0].message.content.strip()
                    additional_bullets = [line for line in additional_content.split('\n') 
                                        if line.strip().startswith('-')]
                    bullet_points.extend(additional_bullets[:min_bullets - len(bullet_points)])
                
                return '\n'.join(bullet_points[:4])  # Return max 4 bullet points
                
            except Exception as e:
                print(f"⚠️ Error generating slide content: {str(e)}")
                # Return default bullet points if generation fails
                return """- Important point about the topic
- Key concept to remember
- Additional relevant information"""
        
        # Generate each slide with specific content
        slides = []
        
        # Slide 1: Introduction
        slide_title = f"Introduction to {topic}"
        intro_prompt = f"""
        Create an introduction slide about: {topic}
        
        Include 3 specific bullet points that:
        1. Clearly explain what {topic} is
        2. State why it's important or relevant
        3. Provide an interesting fact or statistic
        
        Format as markdown bullet points with '- ' at the start of each line.
        """
        intro_content = generate_slide_content(intro_prompt, min_bullets=3)
        # Ensure we have at least 3 bullet points
        bullet_points = [line for line in intro_content.split('\n') if line.strip().startswith('-')]
        if len(bullet_points) < 3:
            bullet_points.extend([
                f"- Important aspect of {topic}",
                f"- Why {topic} matters in daily life",
                f"- Key consideration about {topic}"
            ][:3 - len(bullet_points)])
        slides.append(f"## {slide_title}\n" + '\n'.join(bullet_points[:3]))
        
        # Slide 2: Key Concepts
        slide_title = f"Key Concepts About {topic}"
        concepts_prompt = f"""
        List 3 key concepts about: {topic}
        
        For each concept, provide one clear, specific bullet point that:
        1. Names the concept
        2. Explains it simply
        3. Says why it matters
        
        Format as markdown bullet points with '- ' at the start of each line.
        """
        concepts_content = generate_slide_content(concepts_prompt, min_bullets=3)
        bullet_points = [line for line in concepts_content.split('\n') if line.strip().startswith('-')]
        if len(bullet_points) < 3:
            bullet_points.extend([
                f"- Key concept 1 about {topic} and its significance",
                f"- Important aspect of {topic} and its impact",
                f"- Critical consideration regarding {topic}"
            ][:3 - len(bullet_points)])
        
        # Ensure we have exactly 3 bullet points
        slides.append(f"## {slide_title}\n" + '\n'.join(bullet_points[:3]))
        
        # Slide 3: How It Works
        process_prompt = f"""
        Explain how {topic} works in 3 simple, specific steps.
        
        For each step, provide one clear bullet point that:
        1. Names the step
        2. Explains what happens
        3. Why it's important
        
        Format as markdown bullet points with '- ' at the start of each line.
        """
        process_content = generate_slide_content(process_prompt, min_bullets=3)
        bullet_points = [line for line in process_content.split('\n') if line.strip().startswith('-')]
        if len(bullet_points) < 3:
            bullet_points.extend([
                f"- Step 1: Initial process of {topic}",
                f"- Step 2: Key mechanisms in {topic}",
                f"- Step 3: Final outcomes of {topic}"
            ][:3 - len(bullet_points)])
        slides.append(f"## How {topic} Works\n" + '\n'.join(bullet_points[:3]))
        
        # Slide 4: Examples
        examples_prompt = f"""
        Provide 3 specific, real-world examples of {topic}.
        
        For each example, include one bullet point that:
        1. Names the example
        2. Briefly describes it
        3. Explains its relevance
        
        Format as markdown bullet points with '- ' at the start of each line.
        """
        examples_content = generate_slide_content(examples_prompt, min_bullets=3)
        bullet_points = [line for line in examples_content.split('\n') if line.strip().startswith('-')]
        if len(bullet_points) < 3:
            bullet_points.extend([
                f"- Example 1: Real-world case of {topic}",
                f"- Example 2: Common situation involving {topic}",
                f"- Example 3: Well-known instance of {topic}"
            ][:3 - len(bullet_points)])
        slides.append(f"## Examples of {topic}\n" + '\n'.join(bullet_points[:3]))
        
        # Slide 5: Summary
        summary_prompt = f"""
        Create a summary about {topic} with 3 key takeaways.
        
        For each takeaway, provide one bullet point that:
        1. States an important fact
        2. Explains its significance
        3. Suggests why it matters
        
        Format as markdown bullet points with '- ' at the start of each line.
        """
        summary_content = generate_slide_content(summary_prompt, min_bullets=3)
        bullet_points = [line for line in summary_content.split('\n') if line.strip().startswith('-')]
        if len(bullet_points) < 3:
            bullet_points.extend([
                f"- Key takeaway 1 about {topic}",
                f"- Important consideration about {topic}",
                f"- Final thought on {topic}"
            ][:3 - len(bullet_points)])
        slides.append(f"## Summary: {topic}\n" + '\n'.join(bullet_points[:3]))
        
        # Clean up any remaining placeholders
        cleaned_slides = []
        for slide in slides:
            # Remove any lines containing placeholders
            lines = [line for line in slide.split('\n') 
                    if not any(ph in line.lower() for ph in ['key concept', 'reason ', 'example ', 'step ', 'point '])]
            cleaned_slide = '\n'.join(lines)
            cleaned_slides.append(cleaned_slide)
        
        return cleaned_slides
        
        
    except Exception as e:
        print(f"Error generating slides: {str(e)}")
        # Return default slides in case of error
        return [
            f"# {topic}\n## Introduction",
            f"## What is {topic}?\n- Key concept 1\n- Key concept 2",
            f"## Why is {topic} important?\n- Reason 1\n- Reason 2"
        ]

def generate_narration(slides: list[str]) -> list[str]:
    """Generate narration for each slide using DeepSeek."""
    try:
        client = get_deepseek_client()  # Get client at runtime
        MODEL = "deepseek-chat"  # Model to use for narration
        
        narration_prompt = (
            f"There are {len(slides)} slides below. Each starts with a heading.\n\n"
            + "\n\n".join(f"--- SLIDE {i+1} ---\n{slide}" for i, slide in enumerate(slides))
            + "\n\nWrite exactly one engaging GCSE‑level narration per slide, 60–90 words each. "
            "Return ONLY a valid JSON array of narration strings — no code blocks, no extra text, no explanations, no markdown. Just the array. "
            "If a slide is not suitable for narration, return an empty string for that slide."
        )
        
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful narrator for educational slides."},
                {"role": "user", "content": narration_prompt}
            ],
            temperature=0.7
        )
        narration_raw = response.choices[0].message.content
        import re
        narrations = None
        try:
            narrations = json.loads(narration_raw)
        except Exception:
            # Try to extract first JSON array from anywhere in the output
            match = re.search(r'\[.*?\]', narration_raw, re.DOTALL)
            if match:
                try:
                    narrations = json.loads(match.group(0))
                except Exception as e2:
                    print(f"Secondary JSON extraction failed: {str(e2)}")
                    narrations = None
        if not isinstance(narrations, list):
            print(f"Narration extraction failed. Raw output:\n{narration_raw}")
            narrations = []
        # Fill or trim narrations to match slides
        if len(narrations) < len(slides):
            narrations += ["Please review this slide carefully."] * (len(slides) - len(narrations))
        elif len(narrations) > len(slides):
            narrations = narrations[:len(slides)]
        if not narrations:
            raise RuntimeError("Could not extract any narrations from model output.")
        return narrations

    except Exception as e:
        print(f"Error generating narration: {str(e)}")
        # Fallback: return a default narration for each slide
        return ["Please review this slide carefully."] * len(slides)
        raise
