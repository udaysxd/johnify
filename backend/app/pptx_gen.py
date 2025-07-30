import subprocess
from pathlib import Path
from pptx import Presentation
import shutil
import time
import os
import comtypes.client

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
        
        # Run Marp to convert markdown to PPTX
        MARP = r"C:\Users\uday\AppData\Roaming\npm\marp.cmd"
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

def convert_pptx_to_images(pptx: Path, out_dir: Path) -> Path:
    """
    Convert PPTX slides to PNG images using Microsoft PowerPoint.
    
    Args:
        pptx: Path to the PowerPoint file
        out_dir: Directory to save the output PNG files
        
    Returns:
        Path: Directory containing the exported PNG files
        
    Raises:
        Exception: If there's an error during conversion
    """
    import pythoncom
    
    print(f"\n🔄 Starting PPTX to PNG conversion for: {pptx}")
    
    # Ensure paths are absolute
    pptx = Path(pptx).resolve()
    out_dir = Path(out_dir).resolve()
    
    # Create fresh output directory
    out_dir = fresh_dir(out_dir)
    print(f"📁 Output directory: {out_dir}")
    
    # Initialize COM objects
    pp = None
    pres = None
    
    try:
        # Initialize COM
        pythoncom.CoInitialize()
        
        # Create PowerPoint application instance
        print("🚀 Starting PowerPoint...")
        pp = comtypes.client.CreateObject("PowerPoint.Application")
        pp.Visible = True
        
        # Open the presentation
        print(f"📂 Opening presentation: {pptx.name}")
        pres = pp.Presentations.Open(str(pptx), WithWindow=False)  # Run in background
        
        # Wait for PowerPoint to be ready
        time.sleep(2)
        
        # Export each slide as PNG
        print(f"🖼️ Exporting {len(pres.Slides)} slides...")
        for i, slide in enumerate(pres.Slides, 1):
            png_path = out_dir / f"slide_{i:03d}.png"
            try:
                print(f"   • Exporting slide {i} to {png_path.name}")
                slide.Export(str(png_path), "PNG")
                time.sleep(0.5)  # Small delay between exports
                
                # Verify the file was created
                if not png_path.exists() or png_path.stat().st_size == 0:
                    print(f"   ⚠️ Warning: Slide {i} export may have failed - file is empty")
                    
            except Exception as e:
                print(f"   ⚠️ Error exporting slide {i}: {str(e)}")
                continue
                
        print(f"✅ Successfully exported {len(pres.Slides)} slides to {out_dir}")
        return out_dir
        
    except Exception as e:
        error_msg = f"❌ Error during PPTX to PNG conversion: {str(e)}"
        print(error_msg)
        raise Exception(error_msg) from e
        
    finally:
        # Clean up PowerPoint objects
        try:
            if pres:
                pres.Close()
            if pp:
                pp.Quit()
        except Exception as e:
            print(f"⚠️ Warning during PowerPoint cleanup: {str(e)}")
        
        # Uninitialize COM
        pythoncom.CoUninitialize()
        print("🔌 Released PowerPoint resources")
