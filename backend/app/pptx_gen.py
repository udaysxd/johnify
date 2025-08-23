import subprocess
from pathlib import Path
from pptx import Presentation
import shutil
import time
import os
import sys

# Cross-platform Marp CLI command
if sys.platform == "win32":
    MARP_CANDIDATES = ["marp.cmd", "marp"]
else:
    MARP_CANDIDATES = ["marp"]

def find_marp_cli():
    """Find a working Marp CLI command in PATH."""
    for marp in MARP_CANDIDATES:
        if shutil.which(marp):
            return marp
    raise RuntimeError("Marp CLI not found in PATH. Please install it globally with 'npm install -g @marp-team/marp-cli'.")


def fresh_dir(path: str):
    """Create a fresh directory, removing any existing contents."""
    p = Path(path)
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)
    return p

def markdown_to_pptx(md_path: Path, pptx_path: Path):
    """
    Convert markdown file to PowerPoint presentation using Marp.
    
    Args:
        md_path: Path to the markdown file
        pptx_path: Path where the PowerPoint file should be saved
    """
    import subprocess, sys, os, shutil
    try:
        # Ensure paths are absolute
        md_path = md_path.absolute()
        pptx_path = pptx_path.absolute()

        # Debug: Print Node.js version, Marp CLI path, and CWD
        try:
            print("[DEBUG] Node.js version:")
            print(subprocess.check_output(["node", "--version"], shell=True).decode())
        except Exception as e:
            print(f"[DEBUG] Could not get Node.js version: {e}")
        try:
            print(f"[DEBUG] Marp CLI path: {shutil.which('marp.cmd') or shutil.which('marp')}")
        except Exception as e:
            print(f"[DEBUG] Could not get Marp CLI path: {e}")
        print(f"[DEBUG] Working directory: {os.getcwd()}")

        print(f"\n🔧 Starting PPTX generation")
        print(f"  Input MD: {md_path}")
        print(f"  Output PPTX: {pptx_path}")
        
        # Ensure input file exists
        if not md_path.exists():
            raise FileNotFoundError(f"Markdown file not found: {md_path}")
            
        # Read and validate markdown content
        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
            
        if not md_content.strip():
            raise ValueError("Markdown file is empty")
            
        print("✓ Markdown file is valid")
        
        # Ensure output directory exists
        pptx_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Run Marp to convert markdown to PPTX (cross-platform)
        try:
            MARP = find_marp_cli()
        except Exception as e:
            raise RuntimeError(f"Marp CLI not found: {e}")
        chrome_path_env = os.environ.get('PUPPETEER_EXECUTABLE_PATH') or os.environ.get('CHROME_PATH')
        # On Windows, try to auto-detect Chrome/Edge if not provided
        if not chrome_path_env and sys.platform == 'win32':
            win_candidates = [
                r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
                r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
                r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
            ]
            for p in win_candidates:
                if os.path.exists(p):
                    chrome_path_env = p
                    break
        # Build command with optional chrome-path only if it exists
        cmd = [
            MARP,
            str(md_path),
            '--allow-local-files',
            '--theme', 'default',
            '--pptx',
            '--timeout', '180000',  # 3 minutes timeout
            '--verbose',
            '--output', str(pptx_path)
        ]
        if chrome_path_env and os.path.exists(chrome_path_env):
            cmd.extend(['--chrome-path', chrome_path_env])
        
        print("\n🚀 Running Marp command:")
        print("  " + " ".join(f'"{arg}"' if ' ' in arg else arg for arg in cmd))
        
        env = os.environ.copy()
        # Only set PUPPETEER_EXECUTABLE_PATH if it points to a real file
        if chrome_path_env and os.path.exists(chrome_path_env):
            env.setdefault('PUPPETEER_EXECUTABLE_PATH', chrome_path_env)
            env.setdefault('PUPPETEER_SKIP_DOWNLOAD', '1')
        # Linux container hardening flags
        if sys.platform != 'win32':
            env.setdefault('CHROME_NO_SANDBOX', '1')
            env.setdefault('CHROME_DISABLE_GPU', '1')
            env.setdefault('CHROMIUM_FLAGS', '--no-sandbox --disable-gpu --disable-dev-shm-usage')

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env
        )
        
        # Log command output
        if result.stdout:
            print("\n📋 Marp stdout:")
            print(result.stdout)
        if result.stderr:
            print("\n⚠️  Marp stderr:")
            print(result.stderr)
            
        # Check if command was successful
        if result.returncode != 0:
            error_msg = f"Marp command failed with exit code {result.returncode}"
            if result.stderr:
                error_msg += f"\n{result.stderr}"
            raise RuntimeError(error_msg)
        
        # Verify PPTX was created
        if not pptx_path.exists():
            raise FileNotFoundError(f"PPTX file was not created: {pptx_path}")
            
        # Verify PPTX content
        try:
            prs = Presentation(pptx_path)
            slide_count = len(prs.slides)
            print(f"\n✅ Successfully created PPTX with {slide_count} slides")
            return pptx_path
            
        except Exception as e:
            raise RuntimeError(f"Failed to verify PPTX content: {str(e)}")
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Marp command failed with return code {e.returncode}"
        if e.output:
            error_msg += f"\nOutput: {e.output}"
        if e.stderr:
            error_msg += f"\nError: {e.stderr}"
        raise RuntimeError(error_msg) from e
        
    except Exception as e:
        raise RuntimeError(f"Error converting markdown to PPTX: {str(e)}") from e

def export_slides_to_png_with_marp(md_path: Path, out_dir: Path, timeout_seconds: int = 180):
    """
    Export slide images as PNGs using Marp CLI from markdown file.
    This works on both Windows and Linux as long as Marp CLI is installed.
    
    Args:
        md_path: Path to the markdown file
        out_dir: Directory to save the output PNG files
        timeout_seconds: Maximum time to wait for Marp CLI to complete
    """
    md_path = Path(md_path).absolute()
    out_dir = Path(out_dir).absolute()
    out_dir.mkdir(parents=True, exist_ok=True)
    pngs = []

    try:
        MARP = find_marp_cli()
    except Exception as e:
        print(f"⚠️  Marp CLI not found: {e}")
        return pngs

    # Always run Marp CLI in the markdown's directory, output to local 'images' folder
    chrome_path_env = os.environ.get('PUPPETEER_EXECUTABLE_PATH') or os.environ.get('CHROME_PATH')
    cmd = [
        MARP, 
        md_path.name, 
        "--images", "png", 
        "--output", "images",
        "--allow-local-files",
        "--html",
        "--timeout", str(timeout_seconds * 1000),
        "--verbose",
    ]
    if chrome_path_env and os.path.exists(chrome_path_env):
        cmd.extend(["--chrome-path", chrome_path_env])
    # Only add Chromium raw flags on non-Windows
    if sys.platform != 'win32':
        cmd.extend([
            "--",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage"
        ])
    
    print("\n🚀 Running Marp CLI for PNG export:")
    print(f"  Working directory: {md_path.parent}")
    print("  Command: " + " ".join(f'"{arg}"' if ' ' in arg else arg for arg in cmd))

    try:
        # Run with timeout to prevent hanging
        env = os.environ.copy()
        # Only configure Puppeteer executable if it's valid; otherwise let Marp manage Chromium
        if chrome_path_env and os.path.exists(chrome_path_env):
            env.setdefault('PUPPETEER_EXECUTABLE_PATH', chrome_path_env)
            env.setdefault('PUPPETEER_SKIP_DOWNLOAD', '1')
        if sys.platform != 'win32':
            env.setdefault('CHROME_NO_SANDBOX', '1')
            env.setdefault('CHROME_DISABLE_GPU', '1')
            env.setdefault('CHROMIUM_FLAGS', '--no-sandbox --disable-gpu --disable-dev-shm-usage')

        result = subprocess.run(
            cmd,
            cwd=str(md_path.parent),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout_seconds,
            env=env
        )
    except subprocess.TimeoutExpired as e:
        # Surface timeout as an error for upstream handling
        msg = (
            f"Marp CLI timed out after {timeout_seconds} seconds while exporting PNGs.\n"
            f"md_path={md_path} cwd={md_path.parent} command={' '.join(cmd)}"
        )
        print(f"⚠️  {msg}")
        raise RuntimeError(msg) from e
    except Exception as e:
        print(f"⚠️  Error running Marp CLI: {e}")
        return pngs
    # Look for output files in the expected locations
    work_dir = md_path.parent
    
    # Debug: List all files in the working directory
    print("\n🔍 Files in working directory:")
    for f in work_dir.glob('*'):
        print(f"  - {f.name} (size: {f.stat().st_size if f.is_file() else 'dir'})")
    
    # Marp CLI can output in different formats:
    # 1. images.001, images.002, etc. (no extension)
    # 2. images.001.png, images.002.png, etc.
    # 3. In an 'images' subdirectory
    # 4. Directly as 001.png, 002.png, etc.
    image_files = []
    
    # First, check for files like 001.png, 002.png, etc. (direct output)
    for f in work_dir.glob('[0-9][0-9][0-9].png'):
        if f.is_file() and f.stat().st_size > 0:
            image_files.append(f)
            print(f"Found direct PNG file: {f}")
    
    # Then check for files like images.001, images.002, etc.
    for f in work_dir.glob('images.[0-9][0-9][0-9]'):
        if f.is_file() and f.stat().st_size > 0:
            image_files.append(f)
            print(f"Found numbered file: {f}")
    
    # Then check for files like images.001.png, images.002.png, etc.
    for f in work_dir.glob('images.[0-9][0-9][0-9].png'):
        if f.is_file() and f.stat().st_size > 0 and f not in image_files:
            image_files.append(f)
            print(f"Found numbered PNG file: {f}")
    
    # Then check the images subdirectory
    images_dir = work_dir / 'images'
    if images_dir.exists() and images_dir.is_dir():
        print(f"\n🔍 Files in {images_dir}:")
        for f in images_dir.glob('*'):
            print(f"  - {f.name} (size: {f.stat().st_size if f.is_file() else 'dir'})")
            if f.is_file() and (f.suffix.lower() == '.png' or not f.suffix) and f.stat().st_size > 0:
                image_files.append(f)
                print(f"Found file in images directory: {f}")
    
    # Also check for any PNG files in the root directory
    for f in work_dir.glob('*.png'):
        if f.is_file() and f.stat().st_size > 0 and f not in image_files:
            image_files.append(f)
            print(f"Found PNG file in root: {f}")
            
    # If we still don't have any images, try one more pattern that Marp might use
    if not image_files:
        for f in work_dir.glob('*.png'):
            if f.is_file() and f.stat().st_size > 0 and f not in image_files:
                image_files.append(f)
                print(f"Found additional PNG file: {f}")
                
    # Debug output
    if result and result.stdout:
        print("\n📋 Marp PNG export stdout:")
        print(result.stdout.strip())
    if result and result.stderr:
        print("\n⚠️  Marp PNG export stderr:")
        print(result.stderr.strip())
    # If Marp CLI failed, raise with captured output to surface the root cause
    if result and result.returncode != 0:
        err = [
            f"Marp PNG export failed with exit code {result.returncode}",
            ("STDOUT:\n" + result.stdout.strip()) if result.stdout else "",
            ("STDERR:\n" + result.stderr.strip()) if result.stderr else "",
        ]
        raise RuntimeError("\n".join([e for e in err if e]))
    
    # Process found images
    if image_files:
        print(f"\n🔍 Found {len(image_files)} potential slide images")
        out_dir.mkdir(parents=True, exist_ok=True)
        
        # Sort files by name to maintain order
        def sort_key(f):
            name = f.stem
            try:
                # Extract number from filenames like images.001 or images.001.png
                num = ''.join(c for c in name if c.isdigit())
                return int(num) if num else 0
            except:
                return 0
        
        image_files.sort(key=sort_key)
        
        # Move and rename files
        for i, imgfile in enumerate(image_files, 1):
            if not imgfile.is_file():
                continue
                
            new_name = out_dir / f"slide_{i:03d}.png"
            try:
                # Verify it's actually a PNG file
                if imgfile.suffix.lower() == '.png' or imgfile.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n':
                    # Use copy + unlink instead of replace for better error handling
                    shutil.copy2(imgfile, new_name)
                    imgfile.unlink()
                    pngs.append(new_name)
                    print(f"✅ Saved slide {i}: {new_name}")
                else:
                    print(f"⚠️  Skipping non-PNG file: {imgfile}")
            except Exception as e:
                print(f"⚠️  Failed to process {imgfile}: {e}")
    
    if not pngs:
        print("⚠️  No valid slide images were generated. The presentation may be empty or there may be an issue with Marp CLI.")
    else:
        print(f"✅ Successfully exported {len(pngs)} slides to {out_dir}")
    
    return pngs
    return pngs

def convert_pptx_to_images(pptx_path: Path, out_dir: Path, markdown_path: Path = None):
    """
    Convert each slide in a PPTX file to a PNG image in out_dir.
    If markdown_path is provided and Marp CLI is available, use Marp CLI to export PNGs from markdown (cross-platform).
    Otherwise, fallback to python-pptx and Pillow.
    """
    import sys
    from pptx import Presentation
    from pathlib import Path
    import os
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        # Prefer Marp CLI with markdown if available
        if markdown_path is not None:
            export_slides_to_png_with_marp(markdown_path, out_dir)
            print(f"[convert_pptx_to_images] Used Marp CLI to export PNGs from markdown: {markdown_path}")
            return out_dir
        else:
            import traceback
            from datetime import datetime
            print("\n[convert_pptx_to_images] Fallback error triggered!")
            print(f"[convert_pptx_to_images] Time: {datetime.now().isoformat()}")
            print("[convert_pptx_to_images] Full stack trace:")
            traceback.print_stack()
            raise RuntimeError("Marp CLI PNG export is required. No fallback to Pillow/python-pptx allowed.")
    except Exception as e:
        print(f"Error in convert_pptx_to_images: {e}")
        raise

