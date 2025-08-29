import os
import subprocess
import time
import re
import unicodedata
from PIL import Image, ImageDraw, ImageFont
import base64
import textwrap
import math
import urllib.parse
import json
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from .videos import router as videos_router

# Load environment variables first
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from google.cloud import texttospeech
import openai
import requests
from sqlalchemy.orm import Session

# Import local modules
from . import quiz, slidegen, pptx_gen, tts, video, utils, auth, tutor
from . import gcs_utils
from .database import engine, init_db, get_db
from .auth import models, schemas, security
import shutil

def sanitize_filename(filename: str) -> str:
    """
    Sanitize a string to be used as a filename.
    Replaces spaces with underscores and removes invalid characters.
    """
    # Normalize unicode characters
    filename = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
    # Replace spaces and invalid filename characters with underscores
    filename = re.sub(r'[\\/*?:"<>| ]', '_', filename)
    # Remove consecutive underscores and trailing/leading underscores
    filename = re.sub(r'_+', '_', filename).strip('_')
    return filename


# Set up environment
os.environ["PATH"] += os.pathsep + (
    r"C:\Users\uday\Downloads\ffmpeg-7.1.1-essentials_build"
    r"\ffmpeg-7.1.1-essentials_build\bin"
)

# Initialize OpenAI client

# Load environment variables
load_dotenv()

# Set up Google Cloud credentials
creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if creds:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds
# This avoids TypeError if the env var is not set (which happens on GCP if not configured)

# Initialize DeepSeek client
DS_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DS_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY environment variable not set")

client = openai.OpenAI(api_key=DS_KEY, base_url="https://api.deepseek.com")
MODEL = "deepseek-chat"

class LearnRequest(BaseModel):
    topic: str = Field(..., description="The topic for the educational video")
    complexity_level: int = Field(3, ge=1, le=5, description="Complexity level from 1 (basic) to 5 (advanced)")
    user_email: str = Field(None, description="Email of the user generating the video")
    tags: Optional[List[str]] = Field(None, description="Optional precomputed tags to persist with the post")

class QuizRequest(BaseModel):
    topic: str = Field(..., description="The topic for the quiz")
    num_questions: int = Field(10, ge=1, le=50, description="Number of questions to generate")
    difficulty: Optional[str] = Field(None, description="Difficulty level (optional)")

app = FastAPI(title="Johnify API")

# CORS will be configured later in the file - removing duplicate registration

@app.get("/")
def root():
    return {"message": "Backend is running"}

def clean_markdown_text(text):
    """Clean and format markdown text for display."""
    if not text:
        return ""
    
    # Remove YAML front matter (e.g., marp: true, theme: default)
    text = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.DOTALL)
    
    # Remove HTML comments (narration)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    
    # Remove markdown image syntax
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    
    # Replace markdown bold with plain text
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    
    # Remove any remaining markdown links
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    
    # Clean up any multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def _find_ttf_font(preferred: list) -> Optional[str]:
    """Return the first existing TTF path from a list of candidates."""
    for p in preferred:
        try:
            if p and os.path.exists(p):
                return p
        except Exception:
            continue
    return None

def create_simple_slide(text, output_path, width=1920, height=1080, bg_color=(255, 255, 255), 
                      text_color=(0, 0, 0), padding=50, title_size=60, body_size=40, title=None,
                      theme: str | None = None, background_path: str | None = None,
                      image_mode: str = "full", image_alpha: float = 1.0):
    """
    Create a simple slide image with the given text.
    
    Args:
        text: The content to display on the slide (markdown format)
        output_path: Where to save the generated image
        width: Width of the slide in pixels
        height: Height of the slide in pixels
        bg_color: Background color as RGB tuple
        text_color: Text color as RGB tuple
        padding: Padding from edges in pixels
        title_size: Font size for slide title
        body_size: Font size for body text
        title: Optional title for the slide (if None, will be extracted from first line)
    """
    try:
        # Clean and format the markdown
        text = clean_markdown_text(text)
        
        # Create base image and optionally place background/photo
        img = Image.new('RGB', (width, height), color=bg_color)
        right_panel_x0 = None
        if background_path and os.path.exists(background_path):
            try:
                if image_mode == "full":
                    # Full background with adjustable image alpha and dark overlay for readability
                    base = Image.new('RGBA', (width, height), (*bg_color, 255))
                    bg = Image.open(background_path).convert('RGBA').resize((width, height))
                    if image_alpha < 1.0:
                        # Apply alpha to the background image
                        r, g, b, _ = bg.split()
                        a = Image.new('L', (width, height), int(max(0.0, min(1.0, image_alpha)) * 255))
                        bg = Image.merge('RGBA', (r, g, b, a))
                    composed = Image.alpha_composite(base, bg)
                    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 96))
                    composed = Image.alpha_composite(composed, overlay).convert('RGB')
                    img = composed
                elif image_mode == "right_panel":
                    # Place image on the right with a square container and rounded corners
                    # Compute panel bounds
                    panel_margin = max(20, int(width * 0.01))
                    text_col_right_edge = int(width * 0.60)
                    right_panel_x0 = text_col_right_edge + panel_margin
                    right_panel_y0 = panel_margin
                    panel_w = width - right_panel_x0 - panel_margin
                    panel_h_max = height - 2 * panel_margin
                    # Load and fit image preserving aspect ratio into the available panel area
                    bg = Image.open(background_path).convert('RGBA')
                    iw, ih = bg.size
                    target_h = panel_h_max
                    target_w = panel_w
                    scale = min(max(1e-6, target_w) / max(1, iw), max(1e-6, target_h) / max(1, ih))
                    resized = bg.resize((max(1, int(iw * scale)), max(1, int(ih * scale))), Image.LANCZOS)
                    # Apply alpha to image if specified
                    if image_alpha < 1.0:
                        r, g, b, a = resized.split()
                        a = Image.new('L', resized.size, int(max(0.0, min(1.0, image_alpha)) * 255))
                        resized = Image.merge('RGBA', (r, g, b, a))
                    # Create a square container whose size equals the resized image height
                    box_size = min(panel_w, panel_h_max, resized.size[1])
                    panel_img = Image.new('RGBA', (box_size, box_size), (*bg_color, 0))
                    # Center the resized image within the square container
                    px = max(0, (box_size - resized.size[0]) // 2)
                    py = max(0, (box_size - resized.size[1]) // 2)
                    panel_img.paste(resized, (px, py), resized)
                    # Rounded mask for the square container
                    mask = Image.new('L', (box_size, box_size), 0)
                    draw_m = ImageDraw.Draw(mask)
                    radius = max(20, int(box_size * 0.08))
                    draw_m.rounded_rectangle([0, 0, box_size, box_size], radius=radius, fill=255)
                    # Optional subtle shadow for the square image
                    base_rgba = img.convert('RGBA')
                    shadow = Image.new('RGBA', (box_size, box_size), (0, 0, 0, 0))
                    shadow_draw = ImageDraw.Draw(shadow)
                    shadow_draw.rounded_rectangle([0, 0, box_size, box_size], radius=radius, fill=(0,0,0,60))
                    shadow_bg = Image.new('RGBA', base_rgba.size, (0,0,0,0))
                    # Center the square within the right panel area
                    place_x = right_panel_x0 + max(0, (panel_w - box_size) // 2)
                    place_y = right_panel_y0 + max(0, (panel_h_max - box_size) // 2)
                    shadow_bg.paste(shadow, (place_x + 4, place_y + 4), mask)
                    base_rgba = Image.alpha_composite(base_rgba, shadow_bg)
                    # Paste the square panel with mask
                    base_rgba.paste(panel_img, (place_x, place_y), mask)
                    img = base_rgba.convert('RGB')
                else:
                    # Unknown mode; fallback to plain background
                    pass
            except Exception as _bg_err:
                # Fallback to plain background
                img = Image.new('RGB', (width, height), color=bg_color)
        draw = ImageDraw.Draw(img)
        # Text column: for right_panel, use all available left area up to the panel; for full, use nearly full width
        default_text_right = int(width * 0.60) if image_mode != "full" else (width - padding)
        if image_mode == "right_panel":
            if right_panel_x0 is not None:
                # Place text exactly up to the left edge of the image panel
                safe_margin = 0
                text_right = max(padding + 200, right_panel_x0 - safe_margin)
            else:
                # No image panel available; allow text to span nearly full width
                text_right = width - padding
        else:
            text_right = default_text_right
        total_px = max(200, width - 2 * padding)
        # Allow content to extend right up to the image edge (no extra right padding)
        content_px = max(200, text_right - padding)
        # Approximate characters-per-line by scaling a base width to our pixel ratio
        # Allow full-width wrapping when image_mode == 'full'
        ratio_cap = 1.0 if image_mode in ("right_panel", "full") else 0.60
        ratio = max(0.3, min(ratio_cap, content_px / total_px))

        # Special endcard: center the brand text and bypass normal title/content
        if theme == "johnify_endcard":
            try:
                end_text = "Johnify"
                # Choose a large bold font if available
                repo_root = Path(__file__).resolve().parent.parent.parent
                bold_font_paths = [
                    str(repo_root / "backend" / "app" / "assets" / "fonts" / "DejaVuSans-Bold.ttf"),
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    r"C:\\Windows\\Fonts\\arialbd.ttf",
                    r"C:\\Windows\\Fonts\\segoeuib.ttf",
                ]
                end_font = None
                for fp in bold_font_paths:
                    try:
                        if os.path.exists(fp):
                            end_font = ImageFont.truetype(fp, 120)
                            break
                    except Exception:
                        continue
                if end_font is None:
                    end_font = ImageFont.load_default()
                # Measure text
                try:
                    bbox = draw.textbbox((0, 0), end_text, font=end_font)
                    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                except Exception:
                    try:
                        tw = int(draw.textlength(end_text, font=end_font))  # type: ignore[attr-defined]
                        th = 120
                    except Exception:
                        tw, th = 600, 120
                x = max(0, (width - int(tw)) // 2)
                y = max(0, (height - int(th)) // 2)
                # Optional subtle shadow
                draw.text((x + 3, y + 3), end_text, font=end_font, fill=(0, 0, 0))
                draw.text((x, y), end_text, font=end_font, fill=text_color)
                img.save(output_path)
                return True
            except Exception:
                # If special rendering fails, fall back to normal flow
                pass

        # Theming: optional branded background for tutor pipeline
        if theme == "johnify":
            try:
                solid = (247, 184, 1)  # #f7b801
                # Skip drawing the right-side band when using right panel to preserve rounded corners visibility
                if image_mode != "right_panel":
                    band_w = max(1, int(width * 0.056))
                    band_x0 = width - band_w
                    draw.rectangle([(band_x0, 0), (width, height)], fill=solid)

                # Circle slice in the top-left corner using the same solid color
                circle_radius = max(40, int(min(width, height) * 0.06))
                # Place center at (0,0) so only the top-left quarter appears inside the canvas
                cx, cy = 0, 0
                circle_bbox = [cx - circle_radius, cy - circle_radius, cx + circle_radius, cy + circle_radius]
                draw.ellipse(circle_bbox, fill=(247, 184, 1))  # #f7b801
            except Exception as _:
                # Non-fatal; continue without theme if drawing fails
                pass
        
        # Try to load a TrueType font across platforms; avoid tiny default bitmap font
        repo_root = Path(__file__).resolve().parent.parent.parent
        bundled_regular = repo_root / "backend" / "app" / "assets" / "fonts" / "DejaVuSans.ttf"
        bundled_bold = repo_root / "backend" / "app" / "assets" / "fonts" / "DejaVuSans-Bold.ttf"

        linux_regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        linux_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

        # Common Windows fonts
        win_regular_opts = [
            r"C:\\Windows\\Fonts\\segoeui.ttf",
            r"C:\\Windows\\Fonts\\arial.ttf",
            r"C:\\Windows\\Fonts\\Calibri.ttf",
        ]
        win_bold_opts = [
            r"C:\\Windows\\Fonts\\segoeuib.ttf",
            r"C:\\Windows\\Fonts\\arialbd.ttf",
            r"C:\\Windows\\Fonts\\Calibrib.ttf",
        ]

        # Common macOS fonts
        mac_regular_opts = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        ]
        mac_bold_opts = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        ]

        regular_candidates = [
            str(bundled_regular),
            linux_regular,
        ]
        # Extend with OS lists safely
        regular_candidates.extend(win_regular_opts)
        regular_candidates.extend(mac_regular_opts)

        bold_candidates = [
            str(bundled_bold),
            linux_bold,
        ]
        bold_candidates.extend(win_bold_opts)
        bold_candidates.extend(mac_bold_opts)

        regular_path = _find_ttf_font(regular_candidates)
        bold_path = _find_ttf_font(bold_candidates)

        try:
            # Debug which fonts were selected
            print(f"[FONT DEBUG] regular_candidates tried: {regular_candidates}")
            print(f"[FONT DEBUG] bold_candidates tried: {bold_candidates}")
            print(f"[FONT DEBUG] selected regular={regular_path} bold={bold_path}")
            if bold_path:
                title_font = ImageFont.truetype(bold_path, title_size)
            elif regular_path:
                title_font = ImageFont.truetype(regular_path, title_size)
            else:
                raise IOError("No TTF font found for title")

            if regular_path:
                body_font = ImageFont.truetype(regular_path, body_size)
            elif bold_path:
                body_font = ImageFont.truetype(bold_path, body_size)
            else:
                raise IOError("No TTF font found for body")
        except Exception:
            # Final fallback
            title_font = ImageFont.load_default()
            body_font = ImageFont.load_default()
        
        # If title is not provided, try to extract it from the first line
        if title is None:
            lines = [line for line in text.strip().split('\n') if line.strip()]
            title = lines[0] if lines else ""
            content = '\n'.join(lines[1:]) if len(lines) > 1 else text
        else:
            content = text
        
        # Draw title centered within the available text column
        if title:
            base_title_chars = 55 if image_mode == "full" else 40
            title_wrap_width = max(20, int(base_title_chars * ratio))
            title_lines = textwrap.wrap(title, width=title_wrap_width)
            y = padding
            # Column bounds for centering
            col_left = padding
            col_right = (width - padding) if image_mode == "full" else text_right
            last_w = 0
            last_h = 0
            last_x = col_left
            for line in title_lines:
                # Measure and draw centered within the current text column
                _, _, w, h = draw.textbbox((0, 0), line, font=title_font)
                avail = max(10, col_right - col_left)
                x = col_left + max(0, (avail - int(w)) // 2)
                draw.text((x, y), line, font=title_font, fill=text_color)
                last_w, last_h, last_x = int(w), int(h), int(x)
                y += h + 10

            # Underline just beneath the last title line, matching its width
            line_y = y + 10
            draw.line([(last_x, line_y), (last_x + last_w, line_y)], fill=(200, 200, 200), width=2)
            y = line_y + 30
        else:
            y = padding
        
        # Draw content
        if content:
            # Split content into lines and process each line
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            bullet_indent = 30  # Indent for bullet points
            # Wrap to fill the available text column
            base_chars = 90 if image_mode == "full" else (85 if image_mode == "right_panel" else 60)
            wrap_width = max(35, int(base_chars * ratio))
            
            for line in lines:
                # Handle bullet points
                is_bullet = line.startswith('- ')
                line = line[2:] if is_bullet else line
                
                # Split long lines into multiple lines if needed
                wrapped_lines = textwrap.wrap(line, width=wrap_width)
                
                for i, wrapped_line in enumerate(wrapped_lines):
                    x = padding + (bullet_indent if (is_bullet and i == 0) else 0)
                    
                    # Draw bullet for the first line of a bullet point
                    if is_bullet and i == 0:
                        bullet_x = padding + 10
                        bullet_y = y + body_size // 2 - 2
                        draw.ellipse([bullet_x-4, bullet_y-4, bullet_x+4, bullet_y+4], fill=text_color)
                    
                    # Draw the text
                    draw.text((x, y), wrapped_line, font=body_font, fill=text_color)
                    
                    # Move to next line position
                    y += body_size + 5
                
                # Add extra space after each logical line (not wrapped lines)
                y += 10
        
        # Watermark (applied for johnify theme) — skip for endcard/thank-you slide and title slide (full bg)
        if theme == "johnify" and image_mode != "full" and (str(title or "").strip().lower() != "johnify"):
            try:
                wm_text = "johnify"
                # Use a subtle gray color; if transparency is desired, use an overlay
                # Compute text size
                bbox = draw.textbbox((0, 0), wm_text, font=body_font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                wx = max(padding, width - padding - tw)
                wy = max(padding, height - padding - th)
                # Slight shadow for readability
                draw.text((wx + 2, wy + 2), wm_text, font=body_font, fill=(0, 0, 0))
                draw.text((wx, wy), wm_text, font=body_font, fill=(90, 90, 90))
            except Exception:
                pass

        # Save the image
        img.save(output_path)
        return True
        
    except Exception as e:
        print(f"❌ Error generating simple slide: {str(e)}")
        return False

def _generate_pollinations_image(prompt: str, out_path: str, width: int = 1280, height: int = 720, timeout_s: int = 25) -> bool:
    """Try Pollinations image API. Returns True on success."""
    try:
        import urllib.parse
        encoded = urllib.parse.quote(prompt[:200])
        url = f"https://image.pollinations.ai/prompt/{encoded}"
        print(f"[thumb] Pollinations: {url}")
        resp = requests.get(url, timeout=timeout_s)
        resp.raise_for_status()
        with open(out_path, 'wb') as f:
            f.write(resp.content)
        # Ensure non-trivial file
        if os.path.getsize(out_path) < 2048:
            raise RuntimeError("pollinations tiny file")
        # Resize to target
        try:
            with Image.open(out_path) as im:
                im = im.convert('RGB').resize((width, height), Image.LANCZOS)
                im.save(out_path, format='JPEG', quality=86)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[thumb] Pollinations failed: {e}")
        return False

def _generate_hf_image(prompt: str, out_path: str, width: int = 1280, height: int = 720) -> bool:
    """Try Hugging Face Inference API with several models. Requires HUGGINGFACE_TOKEN."""
    try:
        hf_token = os.getenv("HUGGINGFACE_TOKEN")
        if not hf_token:
            print("[thumb] HF token missing; skipping HF step")
            return False
        headers = {"Authorization": f"Bearer {hf_token}"}
        negative = os.getenv("TUTOR_BG_NEGATIVE", "nsfw, text, watermark, logo, low quality, blurry")
        payload = {
            "inputs": prompt,
            "parameters": {
                "negative_prompt": negative,
                "guidance_scale": 6.0,
                "num_inference_steps": 20,
                "width": width,
                "height": height,
            },
        }
        candidates = [
            os.getenv("TUTOR_BG_MODEL", "stabilityai/stable-diffusion-3.5-medium"),
            "stabilityai/sdxl-turbo",
            "stabilityai/stable-diffusion-xl-base-1.0",
            "runwayml/stable-diffusion-v1-5",
        ]
        for model in candidates:
            url = f"https://api-inference.huggingface.co/models/{model}"
            print(f"[thumb] HF model: {model}")
            for attempt in range(1, 5):
                resp = requests.post(url, headers=headers, json=payload, timeout=120)
                ctype = resp.headers.get("content-type", "")
                if resp.status_code == 200 and ctype.startswith("image"):
                    with open(out_path, "wb") as f:
                        f.write(resp.content)
                    # Ensure size
                    try:
                        with Image.open(out_path) as im:
                            if im.size != (width, height):
                                im = im.convert('RGB').resize((width, height), Image.LANCZOS)
                                im.save(out_path, format='JPEG', quality=86)
                    except Exception:
                        pass
                    return True
                if resp.status_code == 202:
                    sleep_s = min(8, 1 + attempt * 2)
                    print(f"[thumb] HF loading (202) attempt={attempt}; sleep {sleep_s}s")
                    time.sleep(sleep_s)
                    continue
                if resp.status_code in (403, 404):
                    print(f"[thumb] HF unavailable {resp.status_code}; next model")
                    break
                try:
                    print(f"[thumb] HF error {resp.status_code}: {resp.text[:150]}")
                except Exception:
                    pass
                break
        return False
    except Exception as e:
        print(f"[thumb] HF exception: {e}")
        return False

def _pil_text_thumbnail(text: str, out_path: str, width: int = 1280, height: int = 720, scale: float = 5.0) -> bool:
    """PIL fallback thumbnail with large title text. Scale increases font size ~5x."""
    try:
        img = Image.new('RGB', (width, height), color=(20, 32, 48))
        draw = ImageDraw.Draw(img)
        title_txt = (text or "").strip()[:120] or "Learning Video"
        # Try truetype fonts with big size, else compute based on default metric
        font = None
        base_size = 24
        try:
            for fp in [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "C:/Windows/Fonts/segoeuib.ttf",
            ]:
                if os.path.exists(fp):
                    font = ImageFont.truetype(fp, int(base_size * scale * 2.5))
                    break
        except Exception:
            font = None
        if font is None:
            try:
                dflt = ImageFont.load_default()
                # Estimate default bbox height then scale
                bb = draw.textbbox((0,0), "Ag", font=dflt)
                dh = max(12, bb[3]-bb[1])
                target_px = int(dh * scale)
                # Try to find a truetype at approx target height
                for sz in [target_px*3, target_px*2, target_px*2, target_px, max(32, target_px)]:
                    for fp in [
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                        "C:/Windows/Fonts/arialbd.ttf",
                        "C:/Windows/Fonts/segoeuib.ttf",
                    ]:
                        if os.path.exists(fp):
                            font = ImageFont.truetype(fp, sz)
                            break
                    if font is not None:
                        break
                if font is None:
                    font = dflt
            except Exception:
                font = ImageFont.load_default()
        # Wrap within padded width
        pad_x = int(width * 0.08)
        max_w = max(100, width - 2 * pad_x)
        def _text_size(s: str):
            try:
                bb = draw.textbbox((0,0), s, font=font)
                return bb[2]-bb[0], bb[3]-bb[1]
            except Exception:
                try:
                    return int(draw.textlength(s, font=font)), 32
                except Exception:
                    return len(s)*14, 32
        words = title_txt.split()
        lines: list[str] = []
        current = ""
        for w in words:
            test = w if not current else current + " " + w
            tw, _ = _text_size(test)
            if tw <= max_w:
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
        # Center vertically
        heights = [ _text_size(ln)[1] for ln in lines ]
        spacing = max(10, int(sum(heights)/max(1,len(heights))/6))
        total_h = sum(heights) + max(0, (len(lines)-1)*spacing)
        y = max(0, (height - int(total_h)) // 2)
        for ln in lines:
            tw, th = _text_size(ln)
            x = pad_x + max(0, (max_w - int(tw)) // 2)
            draw.text((x+3, y+3), ln, fill=(0,0,0), font=font)
            draw.text((x, y), ln, fill=(235,245,255), font=font)
            y += th + spacing
        img.save(out_path, format='JPEG', quality=86)
        print(f"[thumb] PIL fallback saved: {out_path}")
        return True
    except Exception as e:
        print(f"[thumb] PIL fallback failed: {e}")
        return False

def generate_thumbnail_with_fallbacks(topic: str, out_path: str, label: str = "learn") -> bool:
    """Try Pollinations → Hugging Face → Cloudflare → PIL in order."""
    prompt = (
        f"clean minimal educational thumbnail for: {topic} ({label}), without any text, "
        "letters, words, captions, logos, watermarks, signatures, signage, title"
    )
    # 1) Pollinations
    if _generate_pollinations_image(prompt, out_path):
        return True
    # 2) Hugging Face
    if _generate_hf_image(prompt, out_path):
        return True
    # 3) Cloudflare (temporarily set size via env override)
    old_w = os.getenv("CLOUDFLARE_IMG_W")
    old_h = os.getenv("CLOUDFLARE_IMG_H")
    os.environ["CLOUDFLARE_IMG_W"] = "1280"
    os.environ["CLOUDFLARE_IMG_H"] = "720"
    try:
        if generate_cloudflare_image(prompt, out_path):
            return True
    finally:
        if old_w is not None:
            os.environ["CLOUDFLARE_IMG_W"] = old_w
        else:
            os.environ.pop("CLOUDFLARE_IMG_W", None)
        if old_h is not None:
            os.environ["CLOUDFLARE_IMG_H"] = old_h
        else:
            os.environ.pop("CLOUDFLARE_IMG_H", None)
    # 4) PIL fallback (5x larger font)
    return _pil_text_thumbnail(topic, out_path, scale=5.0)

def generate_cloudflare_image(prompt: str, out_path: str, seed: Optional[int] = None) -> bool:
    """Generate an image via Cloudflare AI and save to out_path.

    Relies on environment variables:
      - CLOUDFLARE_ACCOUNT_ID
      - CLOUDFLARE_API_TOKEN
      - CLOUDFLARE_MODEL (optional, default '@cf/black-forest-labs/flux-1-schnell')
    """
    try:
        account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        api_token = os.getenv("CLOUDFLARE_API_TOKEN")
        model = os.getenv("CLOUDFLARE_MODEL", "@cf/black-forest-labs/flux-1-schnell")
        if not account_id or not api_token:
            print("[CF IMG] Missing CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_TOKEN; skipping.")
            return False
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
        # Strengthen prompt to avoid any embedded text on the image
        negative = os.getenv(
            "CLOUDFLARE_NEGATIVE",
            "without any text, letters, words, captions, logos, watermarks, signatures, signage, title, subtitles, numbers"
        )
        full_prompt = f"{prompt}. {negative}" if prompt else negative
        # Enforce square 512x512 outputs (overridable via env)
        w = int(os.getenv("CLOUDFLARE_IMG_W", "512"))
        h = int(os.getenv("CLOUDFLARE_IMG_H", "512"))
        payload = {"prompt": full_prompt, "width": w, "height": h}
        if seed is not None:
            payload["seed"] = seed
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
        resp.raise_for_status()
        ctype = resp.headers.get("Content-Type", "")
        # Helper: force final image dimensions to exactly (w,h)
        def _ensure_size(pth: str, w: int, h: int):
            try:
                from PIL import Image
                with Image.open(pth) as im:
                    if im.size != (w, h):
                        im = im.convert('RGB').resize((w, h), Image.LANCZOS)
                        im.save(pth)
            except Exception:
                pass

        # Case 1: binary image
        if "image/" in ctype:
            with open(out_path, "wb") as f:
                f.write(resp.content)
            ok = os.path.exists(out_path) and os.path.getsize(out_path) > 1024
            if ok:
                _ensure_size(out_path, w, h)
            return ok
        # Case 2: JSON with base64
        try:
            data = resp.json()
            # Try common keys
            b64 = (
                data.get("result", {}).get("image")
                or data.get("image")
                or data.get("result", {}).get("image_base64")
                or data.get("image_base64")
            )
            if b64:
                img_bytes = base64.b64decode(b64)
                with open(out_path, "wb") as f:
                    f.write(img_bytes)
                ok = os.path.exists(out_path) and os.path.getsize(out_path) > 1024
                if ok:
                    _ensure_size(out_path, w, h)
                return ok
        except Exception:
            pass
        # Fallback: write bytes anyway
        with open(out_path, "wb") as f:
            f.write(resp.content)
        ok = os.path.exists(out_path) and os.path.getsize(out_path) > 1024
        if ok:
            _ensure_size(out_path, w, h)
        return ok
    except Exception as e:
        print(f"[CF IMG] Error generating image: {e}")
        return False

# Initialize database tables
init_db()

# --- DB target logging (startup) ---
try:
    db_url = os.getenv("DATABASE_URL", "")
    if db_url:
        # Mask credentials and log host/db
        parsed = urllib.parse.urlparse(db_url)
        host = parsed.hostname or ""
        dbname = (parsed.path or "/").lstrip("/")
        print(f"[DB DEBUG] Connecting to host='{host}' db='{dbname}'")
    else:
        print("[DB DEBUG] DATABASE_URL not set")
except Exception as e:
    print(f"[DB DEBUG] Error parsing DATABASE_URL: {e}")

# Mount the static directory for serving generated videos
import os
from pathlib import Path
# Get the absolute path to the generated directory
# In production (Cloud Run), serve from /app/generated. Locally, keep repo_root/generated.
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT == "production"

if IS_PRODUCTION:
    # Cloud Run: container FS is read-only except /tmp. Use /tmp for generated artifacts.
    base_dir = Path("/tmp")
else:
    # Previous behavior: repo root three levels up from this file
    base_dir = Path(__file__).resolve().parent.parent.parent

generated_dir = base_dir / "generated"

# Create the directory if it doesn't exist
generated_dir.mkdir(exist_ok=True, parents=True)

# Convert to string path for FastAPI (using forward slashes for consistency)
generated_path = str(generated_dir).replace('\\', '/')
print(f"[STATIC DEBUG] ENVIRONMENT={ENVIRONMENT} Serving videos from: {generated_path}")

# Get allowed origins from environment variable or use default
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS", 
    "http://localhost:3000,http://localhost:8000"
).split(",")


# Configure CORS (single, correct middleware)

# Debug logging
print(f"[CORS DEBUG] ENVIRONMENT: {ENVIRONMENT}")
print(f"[CORS DEBUG] IS_PRODUCTION: {IS_PRODUCTION}")

if IS_PRODUCTION:
    origins = [
        "https://johnify.com",
        "https://www.johnify.com",
        "https://johnify-frontend-*.uc.r.appspot.com",  # GCP App Engine domain pattern
        "https://*.web.app",  # Firebase Hosting domain
        "https://*.firebaseapp.com"  # Firebase Auth domain
    ]
    print(f"[CORS DEBUG] Production origins: {origins}")
else:
    origins = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000"
    ]

def custom_cors_middleware(app):
    async def cors_middleware(request: Request, call_next):
        # Handle preflight requests
        if request.method == 'OPTIONS':
            response = JSONResponse(status_code=200, content={"status": "ok"})
        else:
            response = await call_next(request)

        # Get the origin from the request
        origin = request.headers.get('origin')
        
        # Check if origin is in allowed origins or matches a wildcard pattern
        origin_allowed = False
        if origin:
            if origin in origins:
                origin_allowed = True
            else:
                # Check against wildcard patterns
                for pattern in origins:
                    if '*' in pattern:
                        # Convert wildcard pattern to regex safely
                        escaped = re.escape(pattern)
                        regex_pattern = '^' + escaped.replace(r'\*', '.*') + '$'
                        if re.match(regex_pattern, origin):
                            origin_allowed = True
                            break
        
        # Set CORS headers
        if origin_allowed:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
            # Expose headers needed for cross-origin media seeking
            response.headers['Access-Control-Expose-Headers'] = 'Content-Disposition, Authorization, Accept-Ranges, Content-Range'
            response.headers['Access-Control-Max-Age'] = '600'
        
        return response
    
    return cors_middleware

# Add the CORS middleware
app.middleware('http')(custom_cors_middleware(app))

# Add a lightweight middleware to ensure Accept-Ranges for video responses
@app.middleware('http')
async def add_range_headers(request: Request, call_next):
    response = await call_next(request)
    try:
        if request.url.path.startswith('/videos'):
            # Starlette StaticFiles handles range/206; we add explicit header for clients to detect seekability
            if 'Accept-Ranges' not in response.headers:
                response.headers['Accept-Ranges'] = 'bytes'
    except Exception:
        pass
    return response


# Mount the static files with the absolute path
app.mount("/videos", StaticFiles(directory=generated_path), name="videos")

# Add a debug route to check file serving
@app.get("/debug/files/{path:path}")
async def debug_files(path: str):
    file_path = generated_dir / path
    if not file_path.exists():
        # Try to list the parent directory to see what's there
        parent_dir = file_path.parent
        try:
            files = os.listdir(parent_dir) if parent_dir.exists() else []
        except Exception as e:
            files = [f"Error listing directory: {str(e)}"]
        return {
            "error": f"File not found: {file_path}",
            "generated_dir": str(generated_dir),
            "requested_path": path,
            "absolute_path": str(file_path),
            "parent_dir": str(parent_dir),
            "parent_dir_exists": parent_dir.exists(),
            "files_in_parent": files
        }
    return {"exists": True, "path": str(file_path)}

# Add a test endpoint to verify static file serving
@app.get("/test-static")
async def test_static():
    """Test if static files are being served correctly"""
    test_file = "learn_how_to_become_a_billionaire_1753640850/learn_how_to_become_a_billionaire_1753640850.mp4"
    test_path = generated_dir / test_file
    
    return {
        "test_file": test_file,
        "test_path": str(test_path),
        "exists": test_path.exists(),
        "is_file": test_path.is_file() if test_path.exists() else False,
        "test_url": f"/videos/{test_file}",
        "generated_dir": str(generated_dir),
        "cwd": os.getcwd()
    }

# Add a test endpoint to list generated files
@app.get("/test-files")
async def test_files():
    """Test endpoint to list files in the generated directory"""
    try:
        files = []
        for root, dirs, files_list in os.walk(generated_dir):
            rel_path = os.path.relpath(root, generated_dir)
            if rel_path == '.':
                rel_path = ''
            for f in files_list:
                if f.endswith('.mp4'):  # Only list video files
                    rel_file = os.path.join(rel_path, f).replace("\\", "/")
                    files.append({
                        'path': rel_file,
                        'url': f"/videos/{rel_file}"
                    })
        return {
            'generated_dir': str(generated_dir),
            'files': files
        }
    except Exception as e:
        return {"error": str(e), "generated_dir": str(generated_dir)}

# Debug endpoint: show recent user_posts
@app.get("/debug/user-posts")
async def debug_user_posts():
    try:
        from .database import SessionLocal
        from .auth.models import UserPost
        db = SessionLocal()
        rows = (
            db.query(UserPost)
            .order_by(UserPost.post_id.desc())
            .limit(5)
            .all()
        )
        out = [
            {
                "post_id": r.post_id,
                "user_id": r.user_id,
                "post_topic": getattr(r, 'post_topic', None),
                "post_path": getattr(r, 'post_path', None),
                "created_on": str(getattr(r, 'created_on', None)),
            }
            for r in rows
        ]
        return {"count": len(out), "rows": out}
    except Exception as e:
        return {"error": str(e)}
    finally:
        try:
            db.close()
        except Exception:
            pass

# Include authentication routes
app.include_router(auth.auth_router, prefix="/api")

# Include users routes
from .users.router import router as users_router
app.include_router(users_router, prefix="/api/users")

# Include videos routes
from . import videos
app.include_router(videos.router)

# Configure CORS with specific allowed origins and credentials

# Include routers
app.include_router(quiz.router)
app.include_router(tutor.router)

class LearnVideoTask:
    def __init__(self, topic: str, complexity_level: int = 3, user_email: str = None, user_id: Optional[int] = None, tags: Optional[List[str]] = None):
        self.topic = topic
        self.complexity_level = max(1, min(5, complexity_level))  # Clamp between 1-5
        self.safe_topic = sanitize_filename(topic)
        self.timestamp = int(time.time())
        self.output_dir = None
        self.user_email = user_email
        self.user_id = user_id
        # Optional precomputed tags from request
        self.tags: Optional[List[str]] = tags

    def process(self):
        """Process the video generation for the learn endpoint (synchronous)."""
        try:
            # Create output directory
            self.output_dir = f"generated/learn_{self.safe_topic}_{self.timestamp}"
            os.makedirs(self.output_dir, exist_ok=True)
            
            # Generate slides (similar to quiz pipeline)
            print(f"\n1️⃣ Generating slides for topic: {self.topic}")
            slides = slidegen.generate_learn_slides(self.topic, self.complexity_level)
            if not slides:
                raise ValueError("No slides were generated")
            
            # Debug: Print the generated slides
            print("\n📄 Generated slides content:")
            for i, slide in enumerate(slides):
                print(f"\n--- SLIDE {i+1} ---")
                print(slide)
                print("------------------")
            
            print(f"✅ Generated {len(slides)} slides")
            
            # Generate narration using the actual slide content
            print("\n2️⃣ Generating narration...")
            try:
                narrations = slidegen.generate_narration(slides)
                if not narrations:
                    raise ValueError("No narrations were generated")
                    
                # Debug: Print the generated narrations
                print("\n🔊 Generated narrations:")
                for i, narration in enumerate(narrations):
                    print(f"\n--- NARRATION {i+1} ---")
                    print(narration)
                    print("----------------------")
                
                # Ensure we have the same number of narrations as slides
                if len(narrations) != len(slides):
                    print(f"⚠️ Warning: Mismatch between slides ({len(slides)}) and narrations ({len(narrations)})")
                    if len(narrations) < len(slides):
                        narrations.extend(["Please review this concept carefully."] * (len(slides) - len(narrations)))
                    else:
                        narrations = narrations[:len(slides)]
                
                print(f"✅ Generated {len(narrations)} narrations")
                
            except Exception as e:
                print(f"❌ Error generating narrations: {str(e)}")
                print("⚠️ Using default narrations")
                narrations = [f"Please review the content on this slide about {self.topic}."] * len(slides)
            
            # Append a closing endcard slide and narration
            try:
                slides.append("## Johnify\n")
                narrations.append("thanks for learning")
                print("✅ Appended endcard slide and narration")
            except Exception as _:
                pass
            
            # Save slides to markdown with narration metadata
            print("\n3️⃣ Saving slides to markdown...")
            md_file = os.path.join(self.output_dir, "slides.md")
            
            # Create a copy of slides with narration metadata
            slides_with_narration = []
            for i, (slide, narration) in enumerate(zip(slides, narrations)):
                # Ensure slide has proper heading and content
                slide = slide.strip()
                # Only add a default heading if the slide is completely empty or has no heading
                if slide and not any(line.strip().startswith('#') for line in slide.split('\n')[:3]):
                    # Add a default heading if no heading is found in the first few lines
                    slide = f"## {'Introduction' if i == 0 else f'Key Concepts'}\n{slide}"
                
                # Ensure we have bullet points
                if not any(line.strip().startswith('-') for line in slide.split('\n')):
                    # Add default bullet points if none exist
                    slide = f"{slide}\n- Important point 1\n- Key detail 2\n- Additional information"
                
                # Clean up any empty lines at the start/end
                slide = '\n'.join([line for line in slide.split('\n') if line.strip()])
                
                # Add narration as a comment at the end of each slide
                slide_with_narration = f"{slide}\n\n<!-- NARRATION: {narration} -->"
                slides_with_narration.append(slide_with_narration)
            
            # Save the slides with narration metadata
            try:
                with open(md_file, 'w', encoding='utf-8') as f:
                    # Write Marp frontmatter
                    f.write("---\n")
                    f.write("marp: true\n")
                    f.write("theme: default\n")
                    f.write("paginate: true\n")
                    f.write("---\n\n")
                    
                    # Write each slide with proper separation
                    for i, slide in enumerate(slides_with_narration):
                        if i > 0:
                            f.write("\n---\n\n")  # Add separator between slides
                        f.write(slide.strip())
                        # Ensure each slide ends with a newline
                        if not slide.endswith('\n'):
                            f.write('\n')
            except Exception as e:
                print(f"❌ Error saving slides to markdown: {str(e)}")
                raise
            if not os.path.exists(md_file):
                raise FileNotFoundError(f"Failed to save slides to {md_file}")
            print(f"✅ Saved slides to {md_file}")
            
            # Generate images using Python fallback
            print("\n4️⃣ Generating slide images using Python fallback...")
            image_dir = os.path.join(self.output_dir, "images")
            os.makedirs(image_dir, exist_ok=True)
            
            # Create a Tutor-style title slide first (slide_000.png) using a thumbnail background
            try:
                title_png_path = os.path.join(image_dir, "slide_000.png")
                thumb_path = os.path.join(self.output_dir, "thumbnail.jpg")
                # Generate thumbnail early if missing using unified fallbacks
                if not os.path.exists(thumb_path):
                    try:
                        ok = generate_thumbnail_with_fallbacks(self.topic, thumb_path, label="learn")
                        if not ok:
                            raise RuntimeError("All thumbnail fallbacks failed (early)")
                    except Exception as e:
                        print(f"⚠️ (Learn) Early thumbnail failed after fallbacks: {e}")
                # Build title slide from thumbnail
                if os.path.exists(thumb_path):
                    try:
                        bg = Image.open(thumb_path).convert('RGB')
                        bg = bg.resize((1920, 1080))
                        bg = bg.convert('RGBA')
                        overlay = Image.new('RGBA', bg.size, (0, 0, 0, 120))
                        bg = Image.alpha_composite(bg, overlay)
                        draw = ImageDraw.Draw(bg)
                        title_txt = self.topic.strip()
                        # Try common bold fonts large size; fallback to default
                        font = None
                        try:
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
                        # Wrap and center within padded box
                        pad_x = 160
                        max_w = max(100, 1920 - 2 * pad_x)
                        words = title_txt.split()
                        lines: list[str] = []
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
                        # Center vertically
                        line_heights = []
                        for ln in lines:
                            _, th = _text_size(ln)
                            line_heights.append(th)
                        line_spacing = 14
                        total_h = sum(line_heights) + max(0, (len(lines) - 1) * line_spacing)
                        y = max(0, (1080 - int(total_h)) // 2)
                        for ln in lines:
                            tw, th = _text_size(ln)
                            x = pad_x + max(0, (max_w - int(tw)) // 2)
                            draw.text((x + 3, y + 3), ln, fill=(0, 0, 0), font=font)
                            draw.text((x, y), ln, fill=(250, 250, 250), font=font)
                            y += th + line_spacing
                        bg.convert('RGB').save(title_png_path, format='PNG')
                        print(f"(Learn) Title slide created: {title_png_path}")
                    except Exception as te:
                        print(f"⚠️ (Learn) Failed to create title slide: {te}")
            except Exception as e:
                print(f"⚠️ (Learn) Unexpected error while creating title slide: {e}")

            try:
                # Read the markdown file content
                with open(md_file, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
                
                # First, remove the YAML front matter if it exists
                markdown_content = re.sub(r'^---\n.*?\n---\n', '', markdown_content, flags=re.DOTALL)
                
                # Split into slides (separated by ---)
                slide_contents = [s.strip() for s in markdown_content.split('---') if s.strip()]
                
                # Generate an image for each slide
                global_bg_path = None  # Reuse one Cloudflare image across slides (fetched at slide 2)
                for i, slide_content in enumerate(slide_contents, 1):
                    # Clean up the slide content
                    slide_content = slide_content.strip()
                    if not slide_content:
                        continue
                        
                    # Debug: Print the raw slide content
                    print(f"\n🔄 Processing slide {i} content:")
                    print("--- RAW CONTENT START ---")
                    print(slide_content)
                    print("--- RAW CONTENT END ---")
                        
                    # Remove any remaining HTML comments (narration)
                    slide_content = re.sub(r'<!--.*?-->', '', slide_content, flags=re.DOTALL)
                    
                    # Default title in case none is found
                    title = f"Slide {i}"
                    content_lines = []
                    
                    # Split into lines and process each one
                    for line in slide_content.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                            
                        # Check for markdown header (## ) at the start of the line
                        if line.startswith('## '):
                            print(f"\n🔍 Found potential title: {line}")
                            # If we haven't found a title yet, use this as the title
                            if title == f"Slide {i}":
                                title = line[3:].strip()
                                print(f"✅ Using as title: {title}")
                                continue
                                
                        # Add non-title lines to content
                        content_lines.append(line)
                    
                    # Join the content lines back together
                    slide_content = '\n'.join(content_lines)

                    # Enforce character limits to ensure content fits the frame
                    try:
                        max_chars = 1200 if i == 1 else 800
                        if len(slide_content) > max_chars:
                            slide_content = slide_content[:max_chars].rstrip()
                    except Exception:
                        # If any issue occurs during truncation, proceed with unmodified content
                        pass
                    
                    # Debug: Print the final title and content
                    print(f"\n📝 Final for slide {i}:")
                    print(f"Title: {title}")
                    print("Content:")
                    print(slide_content)
                    print("-" * 40)
                    
                    # Generate output path
                    output_path = os.path.join(image_dir, f"slide_{i:03d}.png")
                    
                    # Fetch a single background image from Cloudflare ONLY on slide 1; we display it only on slide 1
                    background_path = None
                    if global_bg_path:
                        background_path = global_bg_path
                    elif i == 1:
                        try:
                            bg_path = os.path.join(image_dir, f"bg_{i:03d}.jpg")
                            success = generate_cloudflare_image(prompt=title, out_path=bg_path)
                            if success:
                                global_bg_path = bg_path
                                background_path = global_bg_path
                        except Exception:
                            background_path = None

                    # Create the slide image with the extracted title and optional background
                    try:
                        # Slide 1: full background at 10% opacity with dark overlay; white text for readability
                        # Slides 2+: show the same image on the right 30% with rounded corners
                        # Last slide (endcard): centered 'Johnify' text, no background
                        is_last = (i == len(slide_contents))
                        if i == 1 and not is_last:
                            img_mode = "full"
                            use_bg = background_path
                            text_col = (255, 255, 255) if use_bg else (0, 0, 0)
                            img_alpha = 0.1 if use_bg else 1.0
                            theme_use = "johnify"
                        elif is_last:
                            img_mode = "full"
                            use_bg = None
                            text_col = (0, 0, 0)
                            img_alpha = 1.0
                            theme_use = "johnify_endcard"
                        else:
                            img_mode = "right_panel"
                            use_bg = background_path  # this will be global_bg_path if it exists
                            text_col = (0, 0, 0)
                            img_alpha = 0.2
                            theme_use = "johnify"
                        create_simple_slide(
                            slide_content,
                            output_path,
                            title=title,
                            theme=theme_use,
                            background_path=use_bg,
                            image_mode=img_mode,
                            text_color=text_col,
                            image_alpha=img_alpha,
                        )
                    except Exception as e:
                        raise RuntimeError(f"Failed to generate slide {i}")
                
                # Verify images were created
                image_files = sorted([str(f) for f in Path(image_dir).glob("*.png")])
                if not image_files:
                    raise FileNotFoundError("No slide images were generated")
                    
                print(f"✅ Generated {len(image_files)} slide images using Python fallback")
                
            except Exception as e:
                print(f"❌ Error in Python fallback slide generation: {str(e)}")
                raise RuntimeError("All slide generation methods failed")
                
            
            # Generate audio for all narrations at once
            print("\n5️⃣ Creating audio files...")
            audio_dir = os.path.join(self.output_dir, "audio")
            
            # Ensure we have valid narrations
            if not narrations:
                raise ValueError("No narrations provided for audio generation")
                
            # Generate all audio files at once using narrations_to_mp3
            try:
                audio_dir_path = tts.narrations_to_mp3(narrations, audio_dir)
                audio_files = sorted([str(f) for f in Path(audio_dir_path).glob("*.mp3")])
                
                if not audio_files:
                    raise FileNotFoundError("No audio files were generated")
                    
                print(f"✅ Generated {len(audio_files)} audio files in {audio_dir}")
                # Ensure title slide is silent: if slide_000.png exists, prepend a silent s000.mp3
                try:
                    title_png = Path(image_dir) / "slide_000.png"
                    silent_mp3 = Path(audio_dir_path) / "s000.mp3"
                    if title_png.exists():
                        # Create a short silent mp3 (3s) only if it doesn't already exist
                        if not silent_mp3.exists() or os.path.getsize(silent_mp3) == 0:
                            print("🔇 Creating silent audio for title slide (s000.mp3, 1.5s)...")
                            subprocess.run([
                                "ffmpeg", "-y",
                                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                                "-t", "1.5",
                                "-c:a", "libmp3lame",
                                str(silent_mp3)
                            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        else:
                            print("ℹ️ Silent title audio already present: s000.mp3")
                        # Refresh audio file list to include s000.mp3
                        audio_files = sorted([str(f) for f in Path(audio_dir_path).glob("*.mp3")])
                        print(f"🎚️ Total audio files after adding title silence: {len(audio_files)}")
                    else:
                        print("ℹ️ No title slide (slide_000.png) detected; skipping silent audio prepend.")
                except Exception as se:
                    print(f"⚠️ Failed to create silent audio for title slide: {se}")
                
                # Get the list of image files that were generated
                image_files = sorted([str(f) for f in Path(image_dir).glob("*.png")])
                
                # Ensure we have matching number of images and audio files
                min_length = min(len(image_files), len(audio_files))
                if min_length == 0:
                    raise ValueError("No valid slides or audio files found")
                
                image_files = image_files[:min_length]
                audio_files = audio_files[:min_length]
                
            except Exception as e:
                print(f"❌ Error in audio generation or file matching: {str(e)}")
                raise
            
            # Generate video
            print("\n7️⃣ Generating video...")
            video_filename = f"learn_{self.safe_topic}_{self.timestamp}.mp4"
            video_path = os.path.join(self.output_dir, video_filename)
            
            # Ensure we have matching number of images and audio files
            min_length = min(len(image_files), len(audio_files))
            if min_length == 0:
                raise ValueError("No valid slides or audio files found")
                
            image_files = image_files[:min_length]
            audio_files = audio_files[:min_length]
            
            # Create video from slides and audio
            try:
                # Ensure the output directory exists
                output_dir = Path(video_path).parent
                output_dir.mkdir(parents=True, exist_ok=True)
                
                # Get directories for images and audio
                img_dir = Path(image_files[0]).parent if image_files else Path(".")
                aud_dir = Path(audio_files[0]).parent if audio_files else Path(".")
                
                # Use the correct function from video module with Path objects
                video.stitch_images_and_audio_to_video(
                    img_dir=img_dir,
                    aud_dir=aud_dir,
                    out_mp4=Path(video_path)
                )
                
                if not os.path.exists(video_path):
                    raise FileNotFoundError(f"Failed to create video at {video_path}")
                
                print(f"✅ Video generated: {video_path}")
            except Exception as e:
                print(f"❌ Error generating video: {str(e)}")
                raise
            
            # Generate thumbnail.jpg using unified fallbacks
            thumb_path = os.path.join(self.output_dir, "thumbnail.jpg")
            if not os.path.exists(thumb_path):
                ok = generate_thumbnail_with_fallbacks(self.topic, thumb_path, label="learn")
                if ok:
                    print(f"✅ Thumbnail saved: {thumb_path}")
                else:
                    print(f"❌ Failed to generate thumbnail even after fallbacks: {thumb_path}")
            else:
                print(f"✅ Thumbnail saved: {thumb_path}")
        except Exception as e:
            error_msg = f"Error in LearnVideoTask: {str(e)}"
            print(error_msg)
            response = {
                "status": "error",
                "message": error_msg,
                "video_url": ""  # Explicitly include video_url for consistent response structure
            }
            print(f"❌ Returning error response: {response}")
            return response

        # If in production, upload artifacts to GCS and use public HTTPS URLs
        gcs_used = False
        gcs_video_gs = ""
        gcs_video_https = ""
        gcs_thumb_https = ""
        if IS_PRODUCTION:
            try:
                # Directory part for GCS under prefix 'content/learn/...'
                gcs_dir = f"learn/learn_{self.safe_topic}_{self.timestamp}"
                up_video = gcs_utils.maybe_upload_and_url(
                    video_path,
                    parts=[gcs_dir, video_filename],
                    content_type="video/mp4",
                )
                gcs_video_gs = up_video.get("gs_url", "")
                gcs_video_https = up_video.get("https_url", "")
                # Thumbnail
                if os.path.exists(thumb_path):
                    up_thumb = gcs_utils.maybe_upload_and_url(
                        thumb_path,
                        parts=[gcs_dir, "thumbnail.jpg"],
                        content_type="image/jpeg",
                    )
                    gcs_thumb_https = up_thumb.get("https_url", "")
                gcs_used = True
            except Exception as e:
                print(f"⚠️ GCS upload failed (learn): {e}")

        # Create a URL for the video (prefer GCS in production)
        if gcs_used and gcs_video_https:
            video_url = gcs_video_https
        else:
            video_url = f"/videos/learn_{self.safe_topic}_{self.timestamp}/{video_filename}"
        
        # Get the database session
        from .database import SessionLocal, get_db
        from .auth.models import User, UserPost
        from sqlalchemy.exc import SQLAlchemyError, IntegrityError
        from datetime import datetime

        # Record the video in user_posts table
        db = None
        try:
            print(f"🔍 Attempting to connect to database...")
            db = SessionLocal()
            print("✅ Successfully connected to database")
            
            # Resolve user_id preference order: explicit user_id > email lookup
            resolved_user_id = None
            if self.user_id is not None:
                resolved_user_id = int(self.user_id)
                print(f"👤 Using provided user_id: {resolved_user_id}")
            elif self.user_email:
                print(f"🔍 Looking for user with email: {self.user_email}")
                u = db.query(User).filter(User.user_email == self.user_email).first()
                if u:
                    resolved_user_id = u.user_id
                    print(f"✅ Found user by email: ID={resolved_user_id}, Email={u.user_email}")
                else:
                    print(f"⚠️ No user found with email: {self.user_email}")

            if resolved_user_id is None:
                print("❌ Could not resolve user_id; skipping DB record creation to avoid wrong ownership.")
            
            if resolved_user_id is not None:
                print(f"📝 Creating new post entry for user ID: {resolved_user_id}")
                print(f"   - Topic: {self.topic}")
                print(f"   - Video Path: {video_path}")
                
                # Create a new post entry
                # Storage semantics:
                # - If we have a public GCS URL, store that (videos API serves it directly)
                # - Else, store a filesystem-style generated-relative path (NOT a /videos URL)
                #   so that `backend/app/videos.py` can resolve it to a served URL
                if gcs_used and gcs_video_https:
                    post_path_value = gcs_video_https
                elif gcs_video_gs:
                    post_path_value = gcs_video_gs
                else:
                    # Ensure generated-relative path (e.g., generated/learn_<topic>_<ts>/file.mp4)
                    rel_generated_dir = f"generated/learn_{self.safe_topic}_{self.timestamp}"
                    rel_video_path = f"{rel_generated_dir}/{video_filename}"
                    post_path_value = rel_video_path

                # Use precomputed tags from request if provided; sanitize and cap to 7
                def _sanitize_tags_in_request(tags_in: Optional[List[str]]) -> List[str]:
                    out: List[str] = []
                    seen = set()
                    for t in (tags_in or []):
                        if not isinstance(t, str):
                            continue
                        s = " ".join(t.strip().lower().split())[:64]
                        # enforce single-word tag by taking only the first token
                        parts = s.split()
                        s = parts[0] if parts else ""
                        if s and s not in seen:
                            seen.add(s)
                            out.append(s)
                    return out[:7]

                tags_value = _sanitize_tags_in_request(getattr(self, "tags", None))

                post = UserPost(
                    user_id=resolved_user_id,
                    post_path=post_path_value,
                    post_topic=self.topic,
                    created_on=datetime.utcnow(),
                    type='learn',
                    public=True,
                    tags=tags_value
                )
                
                db.add(post)
                try:
                    db.commit()
                    db.refresh(post)  # Refresh to get the generated ID
                    print(f"✅ Successfully recorded video in user_posts table with ID: {post.post_id}")
                except IntegrityError as ie:
                    db.rollback()
                    print(f"❌ Integrity error when saving to database: {str(ie)}")
                    raise
                except Exception as e:
                    db.rollback()
                    print(f"❌ Error saving to database: {str(e)}")
                    raise
            else:
                print("❌ No user resolved to associate with the video.")
                
        except SQLAlchemyError as sae:
            print(f"❌ Database error: {str(sae)}")
            if db:
                db.rollback()
            # Re-raise to be caught by the outer exception handler
            raise
        except Exception as e:
            print(f"❌ Unexpected error when saving to database: {str(e)}")
            if db:
                db.rollback()
            # Don't fail the entire request if database recording fails
            # Just log the error and continue
        finally:
            if db:
                try:
                    db.close()
                except Exception as e:
                    print(f"⚠️ Error closing database connection: {str(e)}")

        # Cleanup local temp artifacts in production ONLY if GCS public URL exists
        try:
            if IS_PRODUCTION and gcs_used and gcs_video_https:
                # Remove the generated directory for this job
                if self.output_dir and os.path.exists(self.output_dir):
                    shutil.rmtree(self.output_dir, ignore_errors=True)
                    print(f"🧹 Cleaned up temp dir: {self.output_dir}")
        except Exception as e:
            print(f"⚠️ Cleanup failed: {e}")

        # Return success response with video URL (after DB handling)
        response = {
            "status": "completed",
            "video_url": video_url,
            "thumbnail_url": (gcs_thumb_https if gcs_used and gcs_thumb_https else f"/videos/learn_{self.safe_topic}_{self.timestamp}/thumbnail.jpg"),
            "message": "Video generated successfully"
        }
        print(f"✅ Returning success response: {response}")
        return response


# Learn endpoint
from .auth import security  # ensure security is imported for dependencies

@app.post("/learn")
async def learn_topic(learn_request: LearnRequest, current_user: models.User = Depends(security.get_current_active_user)):
    """
    Generate an educational video for a given topic.
    
    Args:
        topic: The topic to generate a video about
        complexity_level: Integer from 1 (basic) to 5 (advanced)
    
    Returns:
        dict: Always contains status, message, and video_url fields
    """
    # Default error response
    error_response = {
        "status": "error",
        "message": "",
        "video_url": ""
    }
    
    try:
        print(f"\n📝 Received learn request for topic: {learn_request.topic}")
        print(f"📊 Complexity level: {learn_request.complexity_level}")
        
        if not learn_request.topic or not learn_request.topic.strip():
            error_response["message"] = "Topic cannot be empty"
            print(f"❌ {error_response['message']}")
            return error_response
        
        # Always use the authenticated user's email to avoid mismatches and wrong ownership
        task = LearnVideoTask(
            topic=learn_request.topic.strip(),
            complexity_level=learn_request.complexity_level,
            user_email=getattr(current_user, "user_email", None),
            user_id=getattr(current_user, "user_id", None),
            tags=getattr(learn_request, "tags", None),
        )
        
        # Offload CPU/IO-bound processing to a thread so the event loop stays responsive
        result = await asyncio.to_thread(task.process)
        
        if not result or not isinstance(result, dict):
            error_response["message"] = "Invalid response from video generation task"
            print(f"❌ {error_response['message']}")
            return error_response
            
        # Ensure all required fields are present
        if "status" not in result:
            result["status"] = "completed"  # Default status if missing
        if "video_url" not in result:
            result["video_url"] = ""
        if "message" not in result:
            result["message"] = ""
            
        print(f"✅ Learn task completed with status: {result['status']}")
        if result.get("video_url"):
            print(f"📹 Video URL: {result['video_url']}")
            
        print(f"✅ Returning success response: {result}")
        return result
    except Exception as e:
        print(f"❌ Error in learn endpoint: {str(e)}")
        error_response["message"] = str(e)
        return error_response

# Alias endpoint to support Next.js proxy path `/api/*` so cookies are forwarded consistently
@app.post("/api/learn")
async def learn_topic_api_alias(learn_request: LearnRequest, current_user: models.User = Depends(security.get_current_active_user)):
    return await learn_topic(learn_request, current_user)  # delegate to primary handler


class QuizAnswerRequest(BaseModel):
    answers: list[str]  # list of 10 letters a/b/c/d
    questions: list[dict]  # list of original quiz question dicts

def generate_narration(slides: List[str]) -> List[str]:
    """Generate narration script for slides using DeepSeek."""
    try:
        narration_prompt = (
            f"There are {len(slides)} slides below. Each starts with a heading.\n\n"
            + "\n\n".join(f"--- SLIDE {i+1} ---\n{slide}" for i, slide in enumerate(slides))
            + "\n\nWrite exactly one engaging GCSE‑level narration per slide, 60–90 words each. "
            "Return a valid **JSON array** of narration strings — no extra text, only the array. "
            "Example format: [\"Narration for slide 1\", \"Narration for slide 2\", …]."
        )

        print("Generating narration script…")
        narration_raw = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": narration_prompt}],
            temperature=0.7,
        ).choices[0].message.content.strip()

        # Clean up the response
        if narration_raw.startswith("```json"):
            narration_raw = narration_raw.removeprefix("```json").removesuffix("```").strip()
        elif narration_raw.startswith("```"):
            narration_raw = narration_raw.removeprefix("```").removesuffix("```").strip()
        
        narrations = json.loads(narration_raw)
        
        if not isinstance(narrations, list):
            raise ValueError("Expected a JSON array of narration strings")
            
        if len(narrations) != len(slides):
            print(f"⚠️ Warning: Expected {len(slides)} narrations, got {len(narrations)}")
            
        return narrations
        
    except Exception as e:
        print(f"Error generating narrations: {str(e)}")
        return ["Please review this concept carefully."] * len(slides)

@app.post("/generate")
def generate(req: QuizAnswerRequest, bg: BackgroundTasks):
    """
    Submit quiz answers and generate educational content.
    
    Args:
        req: QuizAnswerRequest containing answers
        bg: BackgroundTasks for async processing
    
    Returns:
        dict: Score and pending status
    """
    print(f"\n🔍 Received answers: {req.answers}")
    
    # Grade the answers and get detailed results
    # Debug: Print the incoming answers and questions structure
    print(f"[DEBUG] Incoming answers: {req.answers}")
    if hasattr(req, 'questions'):
        print(f"[DEBUG] Incoming questions: {getattr(req, 'questions')}")
    else:
        print(f"[DEBUG] No questions attribute in request object.")
    result = quiz.administer(req.answers, req.questions)
    print(f"[DEBUG] Grading result: {result}")
    if 'wrong_questions' in result:
        print(f"[DEBUG] Wrong questions: {result['wrong_questions']}")
    score = result["score"]
    total_questions = result["total_questions"]
    wrong_questions = result["wrong_questions"]
    
    print(f"📊 Score: {score}/{total_questions}")
    print(f"❌ Wrong questions: {len(wrong_questions)}")
    
    if not wrong_questions:
        return {"score": f"{score}/{total_questions}", "message": "Perfect! No video necessary."}
    
    print(f"📝 Will generate slides for {len(wrong_questions)} wrong questions")
    
    # Create per-topic output directory (mirroring learn pipeline)
    import time
    from .pptx_gen import export_slides_to_png_with_marp
    from .utils import sanitize_filename
    safe_topic = sanitize_filename(req.questions[0]['q'] if req.questions and 'q' in req.questions[0] else 'quiz')
    timestamp = int(time.time())
    output_dir = Path(f"generated/Quiz_Results/{safe_topic}_{timestamp}")
    output_dir.mkdir(exist_ok=True, parents=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    
    # heavy stuff in background so request returns fast
    def pipeline():
        try:
            print("\n1️⃣ Generating slides...")
            # Transform wrong_questions to expected schema for slidegen
            def extract_correct_answer(qobj):
                opts = qobj.get("opts", {})
                correct_key = qobj.get("a")
                if isinstance(opts, dict) and correct_key:
                    idx = ord(correct_key.lower()) - ord('a')
                    if 0 <= idx < len(opts):
                        # Remove "a) " etc.
                        return opts.get(correct_key, "Unknown")
                return "Unknown"

            slide_inputs = []
            for q in wrong_questions:
                # Map the properties to match what generate_slide_markdown expects
                slide_inputs.append({
                    "question": q.get("question", q.get("q", "No question provided")),
                    "correct_answer": q.get("correctAnswer", q.get("a", "No answer provided")),
                    "explanation": q.get("explanation", "No explanation available"),
                    "options": q.get("options", [])  # Add options if needed for the slides
                })

            slides = slidegen.generate_slide_markdown(slide_inputs)
            if not slides:
                raise ValueError("No slides were generated")
                
            print(f"✅ Generated {len(slides)} slides")
            
            print("\n2️⃣ Saving slides to markdown...")
            md_file = output_dir / "slides.md"
            slidegen.save_slides_to_md(slides, str(md_file))

            if not md_file.exists():
                raise FileNotFoundError(f"Failed to save slides to {md_file}")
            print(f"✅ Saved slides to {md_file}")
            
            print("\n3️⃣ Converting to PPTX...")
            pptx_file = output_dir / "lesson.pptx"
            
            print("\n3️⃣ Converting to PPTX...")
            pptx_file = output_dir / "lesson.pptx"
            
            try:
                # Use npx to run marp-cli
                subprocess.run([
                    "npx", "@marp-team/marp-cli",
                    str(md_file),
                    "--pptx",
                    "--output", str(pptx_file)
                ], check=True, shell=True)
                
                if not pptx_file.exists():
                    raise FileNotFoundError(f"Failed to create PPTX file")
                print(f"✅ Created PPTX: {pptx_file}")
                
            except subprocess.CalledProcessError as e:
                print(f"❌ Error converting to PPTX. Make sure Node.js and npm are installed.")
                print(f"You can install Marp CLI with: npm install -g @marp-team/marp-cli")
                raise
            
            print("\n4️⃣ Generating narration...")
            narrations = generate_narration(slides)
            if not narrations:
                print("⚠️ No narrations generated, using default text")
                narrations = ["Please review this concept carefully."] * len(slides)
            print(f"✅ Generated {len(narrations)} narrations")
            
            print("\n5️⃣ Creating audio...")
            audio_dir = output_dir / "audio"
            audio_dir.mkdir(exist_ok=True)
            
            tts_client = texttospeech.TextToSpeechClient()
            for idx, narration in enumerate(narrations, 1):
                speech = tts_client.synthesize_speech(
                    input=texttospeech.SynthesisInput(text=narration),
                    voice=texttospeech.VoiceSelectionParams(
                        language_code="en-GB",
                        name="en-GB-Standard-A"
                    ),
                    audio_config=texttospeech.AudioConfig(
                        audio_encoding=texttospeech.AudioEncoding.MP3
                    )
                )
                audio_file = audio_dir / f"slide_{idx:03d}.mp3"
                with open(audio_file, "wb") as out:
                    out.write(speech.audio_content)
            
            print(f"✅ Audio files saved to {audio_dir}")
            
            print("\n6️⃣ Converting slides to PNGs...")
            print(f"[DEBUG] About to export PNGs with Marp CLI: md_file={md_file}, images_dir={images_dir}")
            # Use robust Marp CLI PNG export helper (mirroring learn pipeline)
            try:
                export_slides_to_png_with_marp(md_file, images_dir)
            except Exception as e:
                print(f"❌ Error exporting slide images with Marp CLI: {e}")
                raise RuntimeError(f"Failed to export slide images: {e}")
            print(f"✅ PNG slides exported to {images_dir}")
            
            print("\n7️⃣ Stitching video...")
            video_file = output_dir / "lesson_video.mp4"
            
            # Get list of all PNGs and MP3s
            png_files = sorted(images_dir.glob("*.png"))
            mp3_files = sorted(audio_dir.glob("*.mp3"))
            
            if not png_files:
                raise FileNotFoundError("No slide images found")
                
            # Create a list of inputs for ffmpeg
            concat_file = output_dir / "concat.txt"
            
            # Get absolute paths to ensure FFmpeg can find the files
            with open(concat_file, "w") as f:
                for i, png in enumerate(png_files, 1):
                    mp3 = audio_dir / f"slide_{i:03d}.mp3"
                    
                    # Use absolute paths to avoid any working directory issues
                    abs_png = png.absolute()
                    abs_mp3 = mp3.absolute()
                    
                    # Convert Windows paths to forward slashes for ffmpeg
                    png_path = str(abs_png).replace('\\', '/')
                    mp3_path = str(abs_mp3).replace('\\', '/') if mp3.exists() else None
                    
                    if mp3.exists():
                        try:
                            duration = float(subprocess.check_output([
                                "ffprobe", "-v", "error", "-show_entries", 
                                "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                                mp3_path
                            ]).decode().strip())
                        except Exception as e:
                            print(f"⚠️ Error getting duration for {mp3_path}: {e}")
                            duration = 5.0  # Fallback duration
                    else:
                        duration = 5.0  # Default duration if no audio
                    
                    # Write file entry with duration
                    f.write(f"file '{png_path}'\n")
                    f.write(f"duration {duration}\n")
            
            print(f"📄 Created concat file at: {concat_file}")
            print("📝 Concat file contents:")
            with open(concat_file, 'r') as f:
                print(f.read())
            
            # Generate video from images and audio
            print("🚀 Starting video generation...")
            print(f"Working directory: {os.getcwd()}")
            print(f"FFmpeg command: ffmpeg -y -f concat -safe 0 -i {concat_file} -vsync vfr -pix_fmt yuv420p -c:v libx264 -r 30 {video_file}")
            
            try:
                # Create individual video segments for each slide with audio
                temp_dir = output_dir / "temp_segments"
                temp_dir.mkdir(exist_ok=True, parents=True)
                
                # Get list of audio files and match with slides
                audio_files = sorted(audio_dir.glob("*.mp3"))
                if len(png_files) != len(audio_files):
                    print(f"⚠️ Warning: Mismatch between slides ({len(png_files)}) and audio files ({len(audio_files)})")
                
                # Create video segments
                segments = []
                for i, (png, mp3) in enumerate(zip(png_files, audio_files), 1):
                    segment_path = temp_dir / f"segment_{i:03d}.mp4"
                    print(f"🎞️  Creating video segment {i}...")
                    
                    # Get audio duration
                    try:
                        result = subprocess.run([
                            "ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                            str(mp3.absolute())
                        ], capture_output=True, text=True, check=True)
                        duration = float(result.stdout.strip())
                        print(f"  🎧 Audio duration: {duration:.2f}s")
                    except Exception as e:
                        print(f"⚠️  Could not get audio duration: {e}")
                        duration = 5.0  # Default duration
                    
                    # Create video segment with audio
                    try:
                        subprocess.run([
                            "ffmpeg", "-y",
                            "-loop", "1",
                            "-i", str(png.absolute()),
                            "-i", str(mp3.absolute()),
                            "-t", str(duration),
                            "-c:v", "libx264",
                            "-pix_fmt", "yuv420p",
                            "-vf", "fps=30,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1",
                            "-c:a", "aac",
                            "-shortest",
                            str(segment_path.absolute())
                        ], check=True, capture_output=True, text=True)
                        segments.append(segment_path)
                        print(f"  ✅ Created segment: {segment_path.name}")
                    except subprocess.CalledProcessError as e:
                        print(f"❌ Error creating video segment {i}:")
                        print("STDOUT:", e.stdout)
                        print("STDERR:", e.stderr)
                        raise
                
                if not segments:
                    raise RuntimeError("No video segments were created successfully")
                
                # Create concat file
                concat_file = temp_dir / "concat.txt"
                with open(concat_file, 'w') as f:
                    for seg in segments:
                        f.write(f"file '{seg.absolute()}'\n")
                
                print("🔗 Concatenating video segments...")
                try:
                    subprocess.run([
                        "ffmpeg", "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", str(concat_file.absolute()),
                        "-c", "copy",
                        str(video_file.absolute())
                    ], check=True, capture_output=True, text=True)
                    
                    print(f"✅ Video generation completed successfully!")
                    print(f"   Output: {video_file.absolute()}")
                    
                except subprocess.CalledProcessError as e:
                    print("❌ Error concatenating video segments:")
                    print("STDOUT:", e.stdout)
                    print("STDERR:", e.stderr)
                    raise
            except subprocess.CalledProcessError as e:
                print("❌ FFmpeg error:")
                print("STDOUT:", e.stdout)
                print("STDERR:", e.stderr)
                # Try to show the contents of the concat file for debugging
                try:
                    with open(concat_file, 'r') as f:
                        print("\nConcat file contents:", f.read())
                except Exception as fe:
                    print(f"Could not read concat file: {fe}")
                raise
            except subprocess.CalledProcessError as e:
                print(f"❌ FFmpeg error: {e.stderr}")
                raise
            
            print(f"✅ Video saved to: {video_file}")
            
        except Exception as e:
            print(f"Error in pipeline: {str(e)}")
            raise
    
    try:
        bg.add_task(pipeline)
        
        return {
            "score": f"{score}/{total_questions}",
            "message": f"Generating video for {len(wrong_questions)} wrong answers...",
            "wrong_answers": [i for i in result["wrong_indices"]],
            "status": "processing"
        }
    except Exception as e:
        error_msg = f"Failed to start background task: {str(e)}"
        print(f"❌ {error_msg}")
        return {
            "score": f"{score}/{total_questions}",
            "message": error_msg,
            "wrong_answers": [i for i in result.get("wrong_indices", [])],
            "status": "error"
        }




class QuizResponse(BaseModel):
    questions: List[Dict[str, Any]]

@app.post("/generate_quiz", response_model=QuizResponse)
@app.post("/generate-quiz", response_model=QuizResponse)
async def generate_quiz(quiz_request: QuizRequest):
    try:
        # Call DeepSeek API to generate quiz
        client = openai.OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful quiz generator. For each question, provide a clear explanation of why the correct answer is right and the others are wrong."},
                {"role": "user", "content": f"""Generate {quiz_request.num_questions} multiple choice questions about {quiz_request.topic}. 
                For each question, include:
                - 'q': The question text
                - 'opts': A dictionary of options with keys 'a', 'b', 'c', 'd'
                - 'a': The correct answer key (a/b/c/d)
                - 'explanation': A brief explanation of why the correct answer is right
                
                Example format:
                {{
                    "q": "What is the capital of France?",
                    "opts": {{
                        "a": "London",
                        "b": "Paris",
                        "c": "Berlin",
                        "d": "Madrid"
                    }},
                    "a": "b",
                    "explanation": "Paris is the capital and most populous city of France. London is the capital of the UK, Berlin of Germany, and Madrid of Spain."
                }}
                
                Return the questions as a JSON object with a 'questions' key containing an array of questions.
                """
                }
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        
        # Parse the response
        content = response.choices[0].message.content
        try:
            questions = json.loads(content)
            return questions
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Failed to parse quiz questions")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Add this to your main.py
class VideoRequest(BaseModel):
    topic: str
    questions: List[Dict[str, Any]]
    answers: Dict[str, str]
    # Optional: helps us associate the generated quiz video with a user
    user_email: Optional[str] = None

class QuizRequest(BaseModel):
    topic: str = Field(..., description="The topic for the quiz")
    num_questions: int = Field(10, ge=1, le=50, description="Number of questions to generate")
    difficulty: Optional[str] = Field(None, description="Difficulty level (optional)")

# In-memory job store for async video generation
VIDEO_JOBS: Dict[str, Dict[str, Any]] = {}

def _generate_video_from_request(request: "VideoRequest") -> Dict[str, Any]:
    start_ts = time.time()
    print("\n=== QUIZ VIDEO: worker STARTED ===")
    print(f"topic='{request.topic}' | total_questions={len(request.questions)} | provided_answers={len([a for a in request.answers.values() if a])}")
    """
    Generate a video from quiz results.
    """
    # NOTE: This function contains the previous body of generate_video_endpoint
    try:
        # Prepare wrong answers for slide generation

        wrong_questions = []
        for idx, question in enumerate(request.questions):
            opts = question.get('opts')
            # If opts is a dict, convert to list for slidegen, and keep dict for answer lookup
            if isinstance(opts, dict):
                opts_list = [f"{k}) {v}" for k, v in opts.items()]
                opts_dict = opts
            elif isinstance(opts, list):
                opts_list = opts
                # If opts is a list, create a dict mapping 'a'...'d' to elements for answer lookup
                opts_dict = {chr(ord('a')+i): v for i, v in enumerate(opts) if i < 26}
            else:
                opts_list = []
                opts_dict = {}
            question = {**question, 'opts': opts_list, '_opts_dict': opts_dict}
            # Now use opts_list for slidegen, opts_dict for answer lookup
            question_idx = str(idx)
            user_answer_key = request.answers.get(question_idx)
            correct_answer_key = question.get('a', '').lower()
            
            # Skip if no answer provided
            if not user_answer_key:
                continue
                
            # Normalize answer keys - handle both 'a' and 'a) Some text' formats
            def normalize_key(key: str) -> str:
                if not key:
                    return ''
                # If key is like 'a) Some text', extract just 'a'
                key = str(key).strip()
                if ')' in key:
                    key = key.split(')')[0].strip().lower()
                # Just take the first character in case there's any extra text
                return key[0].lower() if key else ''
            
            # Normalize both keys
            user_key = normalize_key(user_answer_key)
            correct_key = normalize_key(correct_answer_key)
            
            # Debug output
            print(f"\n--- Processing Question {idx} ---")
            print(f"Question: {question.get('q', 'No question text')}")
            print(f"Raw user answer key: '{user_answer_key}'")
            print(f"Raw correct answer key: '{correct_answer_key}'")
            print(f"Normalized user key: '{user_key}'")
            print(f"Normalized correct key: '{correct_key}'")
            print(f"Available options: {question.get('opts', {})}")
            
            # Get the actual answer texts using the original keys from options
            option_keys = list(question.get('_opts_dict', {}).keys())
            
            # Find the correct answer key
            correct_option_key = next((k for k in option_keys if normalize_key(k) == correct_key), '')
            print(f"Found correct option key: '{correct_option_key}'")
            
            # Try to find the user's answer key - first check if user_key is already a valid option
            user_option_key = user_key if user_key in option_keys else ''
            print(f"Initial user option key: '{user_option_key}'")
            
            # If not found, try to find a matching key
            if not user_option_key and user_key:
                user_option_key = next((k for k in option_keys if normalize_key(k) == user_key), '')
                print(f"After normalization, user option key: '{user_option_key}'")
            
            # Get the answer texts
            correct_answer = question['_opts_dict'].get(correct_option_key, f'No correct answer found for key: {correct_key}')
            
            # Handle user answer - if not found, show the raw answer
            if user_option_key:
                user_answer = question['_opts_dict'].get(user_option_key, str(user_answer_key))
                print(f"Found user answer in options: '{user_answer}'")
            else:
                # If we can't find the option, show the raw answer key
                user_answer = f"{user_answer_key}" if user_answer_key else "No answer provided"
                print(f"Using raw user answer: '{user_answer}'")
            
            # Final debug output
            print(f"Final user answer: '{user_answer}' (from key: '{user_option_key}')")
            print(f"Final correct answer: '{correct_answer}' (from key: '{correct_option_key}')")
            
            # Add to wrong questions if answer is incorrect
            if user_key != correct_key:
                wrong_questions.append({
                    "question": question.get('q', ''),
                    "correct_answer": correct_answer,
                    "user_answer": user_answer,
                    "options": question.get('opts', {}),
                    "explanation": question.get('explanation', ''),
                    "question_number": idx + 1
                })

        total_questions = len(request.questions)
        wrong_count = len(wrong_questions)
        score = total_questions - wrong_count

        if not wrong_questions:
            return {
                "message": "All answers are correct! No video needed.",
                "score": score,
                "total": total_questions,
                "wrong_answers": wrong_count
            }

        # Generate slides from wrong answers
        slides = slidegen.generate_slide_markdown(wrong_questions)
        
        # Import required modules
        from pathlib import Path
        import tempfile
        import shutil
        from . import tts, video
        from . import slidegen as sg
        
        # Sanitize the topic for use in filenames
        sanitized_topic = sanitize_filename(request.topic)
        if not sanitized_topic:
            sanitized_topic = f"quiz_review_{int(time.time())}"
        ts = int(time.time())
            
        # Create output directory under the globally configured generated_dir (timestamped to avoid collisions)
        output_dir = Path(generated_dir) / f"quiz_{sanitized_topic}_{ts}"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Define paths
        md_path = output_dir / "slides.md"
        pptx_path = output_dir / "slides.pptx"
        images_dir = output_dir / "images"
        audio_dir = output_dir / "audio"
        video_path = output_dir / f"{sanitized_topic}_explanation.mp4"
        
        # Clean up existing files
        for path in [md_path, pptx_path, images_dir, audio_dir]:
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        
        # Create necessary directories
        images_dir.mkdir()
        audio_dir.mkdir()
        
        try:
            # 1. Save slides to markdown
            t0 = time.time()
            print(f"[QUIZ VIDEO] Step 1: Writing markdown -> {md_path}")
            sg.save_slides_to_md(slides, str(md_path))
            print(f"[QUIZ VIDEO] Step 1 done in {time.time() - t0:.2f}s")
            
            # 2. Generate narration
            t0 = time.time()
            print("[QUIZ VIDEO] Step 2: Generating narrations")
            narrations = sg.generate_narration(slides)
            print(f"[QUIZ VIDEO] Step 2 done in {time.time() - t0:.2f}s | narrations={len(narrations)}")
            
            # 3. Export PNGs from markdown using Marp CLI (robust, no fallback)
            #    We skip PPTX generation in production to avoid Puppeteer default 30s timeouts.
            from . import pptx_gen
            t0 = time.time()
            print(f"[QUIZ VIDEO] Step 3: Marp CLI PNG export | md={md_path} -> dir={images_dir}")
            # Increase timeout for production stability (10 minutes)
            exported_pngs = pptx_gen.export_slides_to_png_with_marp(md_path, images_dir, timeout_seconds=600)
            # Validate images actually exist
            from pathlib import Path as _Path
            png_count = len(exported_pngs) if exported_pngs else 0
            if png_count == 0:
                # Double-check directory contents before failing
                png_files = sorted([str(p) for p in _Path(images_dir).glob('slide_*.png')])
                png_count = len(png_files)
            if png_count == 0:
                raise RuntimeError("No slide images were generated by Marp PNG export")
            print(f"[QUIZ VIDEO] Step 3 done in {time.time() - t0:.2f}s | slides={png_count}")

            # 3b. Create thumbnail: Pollinations first, then fallback to first slide
            thumb_path = _Path(output_dir) / "thumbnail.jpg"
            thumb_ok = False
            # Try Pollinations (aligns with learn flow) with basic retries
            try:
                prompt = f"clean minimal educational thumbnail for: {request.topic} (quiz review), without any text, letters, words, captions, logos, watermarks, signatures, signage, title"
                encoded = urllib.parse.quote(prompt[:200])
                url = f"https://image.pollinations.ai/prompt/{encoded}"
                headers = {"User-Agent": "Johnify/1.0 (+https://johnify.com)"}
                print(f"[QUIZ VIDEO] Pollinations thumbnail: {url}")
                last_err = None
                for attempt in range(3):
                    try:
                        resp = requests.get(url, timeout=25, headers=headers)
                        resp.raise_for_status()
                        with open(thumb_path, 'wb') as f:
                            f.write(resp.content)
                        if thumb_path.exists() and thumb_path.stat().st_size > 1024:
                            print(f"[QUIZ VIDEO] Thumbnail saved via Pollinations (attempt {attempt+1}): {thumb_path}")
                            thumb_ok = True
                            break
                        else:
                            last_err = RuntimeError("Thumbnail too small")
                    except Exception as e:
                        last_err = e
                        time.sleep(1.0 * (attempt + 1))
                if not thumb_ok and last_err:
                    raise last_err
            except Exception as e:
                print(f"[QUIZ VIDEO] Pollinations thumbnail failed after retries: {e}")

            if not thumb_ok:
                try:
                    from PIL import Image as _Image
                    first_slide = sorted(_Path(images_dir).glob('slide_*.png'))[0]
                    with _Image.open(first_slide) as im:
                        im = im.convert('RGB')
                        # Letterbox to 1280x720 while preserving aspect
                        target_w, target_h = 1280, 720
                        im_ratio = im.width / im.height
                        tgt_ratio = target_w / target_h
                        if im_ratio > tgt_ratio:
                            new_w = target_w
                            new_h = int(target_w / im_ratio)
                        else:
                            new_h = target_h
                            new_w = int(target_h * im_ratio)
                        im_resized = im.resize((new_w, new_h))
                        canvas = _Image.new('RGB', (target_w, target_h), color=(20, 32, 48))
                        x = (target_w - new_w) // 2
                        y = (target_h - new_h) // 2
                        canvas.paste(im_resized, (x, y))
                        canvas.save(thumb_path, format='JPEG', quality=85)
                    print(f"[QUIZ VIDEO] Thumbnail saved from first slide: {thumb_path}")
                except Exception as e:
                    print(f"[QUIZ VIDEO] ⚠️ Failed to create thumbnail from slide: {e}")

            # 4. Generate audio for each slide
            t0 = time.time()
            print(f"[QUIZ VIDEO] Step 4: TTS for {len(narrations)} slides -> {audio_dir}")
            tts.narrations_to_mp3(narrations, str(audio_dir))
            print(f"[QUIZ VIDEO] Step 4 done in {time.time() - t0:.2f}s")
            
            # 5. Stitch everything together
            t0 = time.time()
            print(f"[QUIZ VIDEO] Step 5: Stitching images+audio -> {video_path}")
            from .video_quiz import stitch_images_and_audio_to_video_quiz
            stitched_ok = stitch_images_and_audio_to_video_quiz(
                img_dir=images_dir,
                aud_dir=audio_dir,
                out_mp4=video_path
            )
            if not stitched_ok:
                raise RuntimeError("Video stitching failed (images/audio mismatch or ffmpeg error)")
            print(f"[QUIZ VIDEO] Step 5 done in {time.time() - t0:.2f}s")
            
            total_dur = time.time() - start_ts
            print(f"\n✅ QUIZ VIDEO: COMPLETED | out_dir={output_dir} | total_time={total_dur:.2f}s")

            # Record quiz video in user_posts (type='tutor')
            try:
                from .database import SessionLocal
                from .auth.models import User, UserPost
                from sqlalchemy.exc import SQLAlchemyError, IntegrityError
                from datetime import datetime as _dt
                db = SessionLocal()
                try:
                    user = None
                    if request.user_email:
                        user = db.query(User).filter(User.user_email == request.user_email).first()
                    # Do not fallback to first user; require exact email match
                    if not user:
                        print("[QUIZ VIDEO] ❌ No matching user found by email; skipping DB record creation to avoid wrong ownership.")
                    if user:
                        # In production, upload to GCS and store gs://; otherwise store relative generated path
                        rel_post_path = f"generated/quiz_{sanitized_topic}_{ts}/{sanitized_topic}_explanation.mp4"
                        gs_post_path = None
                        try:
                            if IS_PRODUCTION:
                                gcs_dir = f"quiz/quiz_{sanitized_topic}_{ts}"
                                # Upload video
                                up_video = gcs_utils.maybe_upload_and_url(
                                    video_path,
                                    parts=[gcs_dir, f"{sanitized_topic}_explanation.mp4"],
                                    content_type="video/mp4",
                                )
                                gs_post_path = up_video.get("gs_url")
                                # Upload thumbnail if present
                                thumb_local = (Path(output_dir) / "thumbnail.jpg")
                                if thumb_local.exists():
                                    gcs_utils.maybe_upload_and_url(
                                        thumb_local,
                                        parts=[gcs_dir, "thumbnail.jpg"],
                                        content_type="image/jpeg",
                                    )
                        except Exception as e:
                            print(f"⚠️ QUIZ GCS upload failed: {e}")

                        post = UserPost(
                            user_id=user.user_id,
                            post_path=(gs_post_path or rel_post_path),
                            post_topic=request.topic,
                            created_on=_dt.utcnow(),
                            type='tutor',
                            public=True
                        )
                        db.add(post)
                        try:
                            db.commit()
                            db.refresh(post)
                            print(f"✅ Saved quiz post to user_posts id={post.post_id} type='tutor'")
                        except IntegrityError as ie:
                            db.rollback()
                            print(f"❌ Integrity error saving quiz post: {ie}")
                        except Exception as e:
                            db.rollback()
                            print(f"❌ Error saving quiz post: {e}")
                    else:
                        print("⚠️ No user found to associate quiz post")
                finally:
                    try:
                        db.close()
                    except Exception:
                        pass
            except Exception as e:
                print(f"⚠️ Failed to record quiz post: {e}")
            
        except Exception as e:
            print(f"\n❌ QUIZ VIDEO: ERROR | {str(e)}")
            raise
        
        # Cleanup local temp artifacts in production after successful upload/DB write
        try:
            if IS_PRODUCTION:
                if output_dir.exists():
                    shutil.rmtree(output_dir, ignore_errors=True)
                    print(f"[QUIZ VIDEO] 🧹 Cleaned up temp dir: {output_dir}")
        except Exception as e:
            print(f"[QUIZ VIDEO] ⚠️ Cleanup failed: {e}")

        # Prefer GCS public URL in production
        if IS_PRODUCTION:
            gcs_dir = f"quiz/quiz_{sanitized_topic}_{ts}"
            https_url = gcs_utils.public_url(gcs_utils.gcs_object_path(gcs_dir, f"{sanitized_topic}_explanation.mp4"))
            thumb_url = gcs_utils.public_url(gcs_utils.gcs_object_path(gcs_dir, "thumbnail.jpg"))
            return {
                "videos": [{
                    "url": https_url,
                    "title": f"{request.topic} Explanation",
                    "thumbnail_url": thumb_url,
                }],
                "score": score,
                "total": total_questions,
                "wrong_answers": wrong_count,
                "message": "Video generated successfully"
            }
        else:
            video_filename = f"quiz_{sanitized_topic}_{ts}/{sanitized_topic}_explanation.mp4"
            return {
                "videos": [{
                    "url": f"/videos/{video_filename}",
                    "title": f"{request.topic} Explanation"
                }],
                "score": score,
                "total": total_questions,
                "wrong_answers": wrong_count,
                "message": "Video generated successfully"
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-video")
async def generate_video_endpoint(request: VideoRequest):
    print("Video generation endpoint called")
    print(f"Topic: {request.topic}")
    print(f"Number of questions: {len(request.questions)}")
    print(f"Number of wrong answers: {len([a for a in request.answers.values() if a])}")
    # Delegate to the reusable function to preserve existing behavior
    return _generate_video_from_request(request)

@app.post("/generate-video/start")
async def generate_video_start(request: VideoRequest):
    """Kick off video generation asynchronously and return a job_id immediately."""
    import uuid
    import asyncio

    job_id = str(uuid.uuid4())
    VIDEO_JOBS[job_id] = {"status": "queued", "created_at": time.time()}
    print("\n=== QUIZ VIDEO: kickoff REQUESTED ===")
    print(f"job_id={job_id} | topic='{request.topic}' | total_questions={len(request.questions)} | provided_answers={len([a for a in request.answers.values() if a])}")

    async def runner():
        try:
            VIDEO_JOBS[job_id]["status"] = "running"
            print(f"[QUIZ VIDEO] job_id={job_id} status -> running")
            # Run heavy, blocking generation in a thread to keep the event loop responsive
            result = await asyncio.to_thread(_generate_video_from_request, request)
            VIDEO_JOBS[job_id]["result"] = result
            VIDEO_JOBS[job_id]["status"] = "done"
            print(f"[QUIZ VIDEO] job_id={job_id} status -> done")
        except Exception as e:
            VIDEO_JOBS[job_id]["status"] = "error"
            VIDEO_JOBS[job_id]["error"] = str(e)
            print(f"[QUIZ VIDEO] job_id={job_id} status -> error | {e}")

    # Run in background (non-blocking)
    asyncio.create_task(runner())
    print(f"=== QUIZ VIDEO: kickoff ACCEPTED | job_id={job_id} ===")

    return {"job_id": job_id, "status": "queued"}

@app.get("/generate-video/status/{job_id}")
async def generate_video_status(job_id: str):
    job = VIDEO_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    status = job.get("status")
    if status == "done":
        # Return result in same shape the frontend expects
        res = job.get("result", {})
        return {"status": "done", **res}
    if status == "error":
        return {"status": "error", "error": job.get("error", "Unknown error")}
    return {"status": status}
