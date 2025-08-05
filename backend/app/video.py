import subprocess
from pathlib import Path
import os
import json

def get_audio_duration(mp3: Path) -> float:
    """Get duration of MP3 file in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', 
             '-show_format', mp3],
            capture_output=True,
            text=True
        )
        data = json.loads(result.stdout)
        return float(data['format']['duration'])
    except Exception as e:
        print(f"Error getting audio duration: {str(e)}")
        return 0.0

def create_slide_video(img: Path, mp3: Path, out_mp4: Path):
    """Create video segment from image and audio."""
    try:
        subprocess.run([
            "ffmpeg", "-y", "-loop", "1", "-i", str(img), "-i", str(mp3),
            "-t", str(get_audio_duration(mp3)), "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out_mp4)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f" Created video segment: {out_mp4}")
        return out_mp4
    except Exception as e:
        print(f"Error creating video segment: {str(e)}")
        raise

def stitch_images_and_audio_to_video(img_dir: Path, aud_dir: Path, out_mp4: Path):
    """Stitch image and audio segments into final video."""
    import tempfile
    import shutil
    
    temp_dir = Path(tempfile.mkdtemp())
    try:
        img_dir, aud_dir = Path(img_dir), Path(aud_dir)
        imgs = sorted(img_dir.glob("slide_*.png"))
        mp3s = sorted(aud_dir.glob("*.mp3"))  # Match any .mp3 files
        
        if not imgs:
            raise ValueError("No slide images found in the specified directory")
            
        if not mp3s:
            print("⚠️ No audio files found. Creating silent video with slides.")
            # Create a silent audio file with default duration
            silent_mp3 = temp_dir / "silent.mp3"
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-t", "5", "-c:a", "libmp3lame", str(silent_mp3)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            mp3s = [silent_mp3] * len(imgs)
        
        pair_n = min(len(imgs), len(mp3s))
        if len(imgs) != len(mp3s):
            print(f"⚠️ Slides: {len(imgs)} · Audio: {len(mp3s)} (will sync to min)")
        
        segs = []
        for i in range(pair_n):
            seg = temp_dir / f"seg_{i+1:03d}.mp4"
            try:
                create_slide_video(imgs[i], mp3s[i], seg)
                segs.append(seg)
            except Exception as e:
                print(f"⚠️ Failed to create segment {i+1}: {str(e)}")
                continue
        
        if not segs:
            raise ValueError("No valid video segments were created")
            
        concat = temp_dir / "concat.txt"
        with concat.open("w", encoding='utf-8') as f:
            for seg in segs:
                f.write(f"file '{seg.resolve()}'\n")
        
        # Create the output directory if it doesn't exist
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        
        # Use a more compatible encoding for the final video
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
            str(out_mp4)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        print(f"🎬 Final video created: {out_mp4}")
        return out_mp4
        
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error: {e.stderr if hasattr(e, 'stderr') else str(e)}")
        raise
    except Exception as e:
        print(f"Error in video stitching: {str(e)}")
        raise
    finally:
        # Clean up temporary directory
        if 'temp_dir' in locals() and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)