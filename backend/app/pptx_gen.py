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
    try:
        # Ensure paths are absolute
        md_path = md_path.absolute()
        pptx_path = pptx_path.absolute()
        
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
        cmd = [
            MARP,
            str(md_path),
            '--allow-local-files',
            '--theme', 'default',
            '--pptx',
            '--output', str(pptx_path)
        ]
        
        print("\n🚀 Running Marp command:")
        print("  " + " ".join(f'"{arg}"' if ' ' in arg else arg for arg in cmd))
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
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

def export_slides_to_png_with_marp(md_path: Path, out_dir: Path):
    """
    Export slide images as PNGs using Marp CLI from markdown file.
    This works on both Windows and Linux as long as Marp CLI is installed.
    """
    md_path = Path(md_path).absolute()
    out_dir = Path(out_dir).absolute()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        MARP = find_marp_cli()
    except Exception as e:
        raise RuntimeError(f"Marp CLI not found: {e}")

    # Always run Marp CLI in the markdown's directory, output to local 'images' folder
    cmd = [MARP, md_path.name, "--images", "png", "--output", "images"]
    print("\n🚀 Running Marp CLI for PNG export (cwd=md_path.parent):")
    print("  " + " ".join(f'\"{arg}\"' if ' ' in arg else arg for arg in cmd))

    result = subprocess.run(
        cmd,
        cwd=str(md_path.parent),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    # Move/rename Marp output images (images.001, images.002, ...) to out_dir/slide_001.png, ...
    for i in range(1, 100):  # Assume max 99 slides
        src = md_path.parent / f"images.{i:03d}"
        if not src.exists():
            break
        dst = out_dir / f"slide_{i:03d}.png"
        src.replace(dst)
    # Optionally clean up any leftover images.* files
    for f in md_path.parent.glob("images.*"):
        try:
            f.unlink()
        except Exception:
            pass
    if result.stdout:
        print("\n📋 Marp PNG export stdout:")
        print(result.stdout)
    if result.stderr:
        print("\n⚠️  Marp PNG export stderr:")
        print(result.stderr)
    if result.returncode != 0:
        error_msg = f"Marp PNG export failed with exit code {result.returncode}"
        if result.stderr:
            error_msg += f"\n{result.stderr}"
        raise RuntimeError(error_msg)
    # Check if PNGs were created
    pngs = list(out_dir.glob("*.png"))
    if not pngs:
        raise FileNotFoundError(f"No PNG files were created in {out_dir}")
    print(f"✅ Exported {len(pngs)} PNG slides to {out_dir}")
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
            try:
                export_slides_to_png_with_marp(markdown_path, out_dir)
                print(f"[convert_pptx_to_images] Used Marp CLI to export PNGs from markdown: {markdown_path}")
                return out_dir
            except Exception as e:
                print(f"[convert_pptx_to_images] Marp CLI PNG export failed: {e}. Falling back to python-pptx.")
        # Fallback to python-pptx and Pillow
        from PIL import Image, ImageDraw
        prs = Presentation(pptx_path)
        for i, slide in enumerate(prs.slides):
            # Render slide as blank (no text rendering)
            img = Image.new('RGB', (1280, 720), color='white')
            d = ImageDraw.Draw(img)
            d.text((10,10), f"Slide {i+1}", fill=(0,0,0))
            img_path = out_dir / f"slide_{i+1:03d}.png"
            img.save(img_path)
        print(f"[convert_pptx_to_images] Exported {len(prs.slides)} slides as images to {out_dir} (fallback mode)")
        return out_dir
    except Exception as e:
        print(f"Error in convert_pptx_to_images: {e}")
        raise

