import os
import subprocess
import time
import re
import unicodedata
from PIL import Image, ImageDraw, ImageFont
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
from . import quiz, slidegen, pptx_gen, tts, video, utils, auth
from .database import engine, init_db, get_db
from .auth import models, schemas, security

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

def create_simple_slide(text, output_path, width=1920, height=1080, bg_color=(255, 255, 255), 
                      text_color=(0, 0, 0), padding=50, title_size=60, body_size=40, title=None):
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
        
        # Create a new image with white background
        img = Image.new('RGB', (width, height), color=bg_color)
        draw = ImageDraw.Draw(img)
        
        # Try to load a nice font, fall back to default if not available
        try:
            # Prefer DejaVu fonts available in Debian Slim runtime
            title_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", title_size
            )
            body_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", body_size
            )
        except IOError:
            # Fall back to default font if DejaVu isn't available (e.g., local env without package)
            title_font = ImageFont.load_default()
            body_font = ImageFont.load_default()
        
        # If title is not provided, try to extract it from the first line
        if title is None:
            lines = [line for line in text.strip().split('\n') if line.strip()]
            title = lines[0] if lines else ""
            content = '\n'.join(lines[1:]) if len(lines) > 1 else text
        else:
            content = text
        
        # Draw title
        if title:
            title_lines = textwrap.wrap(title, width=40)  # Wrap long titles
            y = padding
            for line in title_lines:
                # Get text size for centering
                _, _, w, h = draw.textbbox((0, 0), line, font=title_font)
                x = (width - w) // 2
                draw.text((x, y), line, font=title_font, fill=text_color)
                y += h + 10
            
            # Add a line under the title
            line_y = y + 10  # Add space after title
            draw.line([(width//4, line_y), (3*width//4, line_y)], fill=(200, 200, 200), width=2)
            y = line_y + 30  # Add more space after the line
        else:
            y = padding
        
        # Draw content
        if content:
            # Split content into lines and process each line
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            bullet_indent = 30  # Indent for bullet points
            
            for line in lines:
                # Handle bullet points
                is_bullet = line.startswith('- ')
                line = line[2:] if is_bullet else line
                
                # Split long lines into multiple lines if needed
                wrapped_lines = textwrap.wrap(line, width=60)
                
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
        
        # Save the image
        img.save(output_path)
        return True
        
    except Exception as e:
        print(f"❌ Error generating simple slide: {str(e)}")
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
    base_dir = Path("/app")
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
                        # Convert pattern to regex
                        regex_pattern = '^' + pattern.replace('.', '\.').replace('*', '.*') + '$'
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

class LearnVideoTask:
    def __init__(self, topic: str, complexity_level: int = 3, user_email: str = None):
        self.topic = topic
        self.complexity_level = max(1, min(5, complexity_level))  # Clamp between 1-5
        self.safe_topic = sanitize_filename(topic)
        self.timestamp = int(time.time())
        self.output_dir = None
        self.user_email = user_email

    async def process(self):
        """Process the video generation for the learn endpoint"""
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
            
            try:
                # Read the markdown file content
                with open(md_file, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
                
                # First, remove the YAML front matter if it exists
                markdown_content = re.sub(r'^---\n.*?\n---\n', '', markdown_content, flags=re.DOTALL)
                
                # Split into slides (separated by ---)
                slide_contents = [s.strip() for s in markdown_content.split('---') if s.strip()]
                
                # Generate an image for each slide
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
                    
                    # Debug: Print the final title and content
                    print(f"\n📝 Final for slide {i}:")
                    print(f"Title: {title}")
                    print("Content:")
                    print(slide_content)
                    print("-" * 40)
                    
                    # Generate output path
                    output_path = os.path.join(image_dir, f"slide_{i:03d}.png")
                    
                    # Create the slide image with the extracted title
                    try:
                        create_simple_slide(slide_content, output_path, title=title)
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
            
            # Create a URL for the video
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
                
                # Debug: Print all users in the database
                all_users = db.query(User).all()
                print(f"🔍 Found {len(all_users)} users in the database")
                for u in all_users:
                    print(f"   - User ID: {u.user_id}, Email: {u.user_email}")
                
                # Find the user by email
                user = None
                if self.user_email:
                    print(f"🔍 Looking for user with email: {self.user_email}")
                    user = db.query(User).filter(User.user_email == self.user_email).first()
                    if user:
                        print(f"✅ Found user by email: ID={user.user_id}, Email={user.user_email}")
                    else:
                        print(f"⚠️ No user found with email: {self.user_email}")
                
                # If no user found with email, get the first user as fallback (for testing)
                if not user and all_users:
                    print("⚠️ No matching user found, using first available user")
                    user = all_users[0]
                    print(f"   - Selected user: ID={user.user_id}, Email={user.user_email}")
                
                if user:
                    print(f"📝 Creating new post entry for user ID: {user.user_id}")
                    print(f"   - Topic: {self.topic}")
                    print(f"   - Video Path: {video_path}")
                    
                    # Create a new post entry
                    post = UserPost(
                        user_id=user.user_id,
                        post_path=video_path,  # Store the local file path
                        post_topic=self.topic,
                        created_on=datetime.utcnow()
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
                    print("❌ No users found in the database to associate with the video")
                    
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
            
            # Return success response with video URL
            response = {
                "status": "completed",
                "video_url": video_url,
                "message": "Video generated successfully"
            }
            print(f"✅ Returning success response: {response}")
            return response
            
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

# Learn endpoint
@app.post("/learn")
async def learn_topic(learn_request: LearnRequest):
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
        
        task = LearnVideoTask(
            topic=learn_request.topic.strip(),
            complexity_level=learn_request.complexity_level,
            user_email=learn_request.user_email
        )
        
        result = await task.process()
        
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
            
        return result
        
    except Exception as e:
        error_response["message"] = f"Error in learn_topic endpoint: {str(e)}"
        print(f"❌ {error_response['message']}")
        return error_response


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
                opts = qobj.get("opts", [])
                correct_key = qobj.get("a")
                if isinstance(opts, list) and correct_key:
                    idx = ord(correct_key.lower()) - ord('a')
                    if 0 <= idx < len(opts):
                        # Remove "a) " etc.
                        return opts[idx].split(")", 1)[-1].strip() if ")" in opts[idx] else opts[idx]
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

class QuizRequest(BaseModel):
    topic: str = Field(..., description="The topic for the quiz")
    num_questions: int = Field(10, ge=1, le=50, description="Number of questions to generate")
    difficulty: Optional[str] = Field(None, description="Difficulty level (optional)")

@app.post("/generate-video")
async def generate_video_endpoint(request: VideoRequest):
    print("Video generation endpoint called")
    print(f"Topic: {request.topic}")
    print(f"Number of questions: {len(request.questions)}")
    print(f"Number of wrong answers: {len([a for a in request.answers.values() if a])}")
    """
    Generate a video from quiz results.
    """
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
            
        # Create output directories under project root
        base_dir = Path(__file__).parent.parent.parent  # Go up to project root
        output_dir = base_dir / "generated" / sanitized_topic
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
            sg.save_slides_to_md(slides, str(md_path))
            
            # 2. Generate narration
            narrations = sg.generate_narration(slides)
            
            # 3. Convert markdown to PPTX (optional, keep if PPTX is needed elsewhere)
            from . import pptx_gen
            pptx_gen.markdown_to_pptx(md_path, pptx_path)

            # 4. Export PNGs from markdown using Marp CLI (robust, no fallback)
            pptx_gen.export_slides_to_png_with_marp(md_path, images_dir)

            # 5. Generate audio for each slide
            tts.narrations_to_mp3(narrations, str(audio_dir))
            
            # 6. Stitch everything together
            from .video_quiz import stitch_images_and_audio_to_video_quiz
            stitch_images_and_audio_to_video_quiz(
                img_dir=images_dir,
                aud_dir=audio_dir,
                out_mp4=video_path
            )
            
            print(f"\n✅ All files saved to: {output_dir}")
            
        except Exception as e:
            print(f"\n❌ Error during video generation: {str(e)}")
            raise
        
        video_filename = f"{sanitized_topic}/{sanitized_topic}_explanation.mp4"
        video_path = output_dir / f"{sanitized_topic}_explanation.mp4"
        
        # Return in the format expected by the frontend
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
