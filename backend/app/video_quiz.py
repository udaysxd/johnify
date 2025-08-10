import subprocess
from pathlib import Path
import os
import json
import tempfile
import shutil

def get_audio_duration_quiz(mp3: Path) -> float:
    """Get duration of MP3 file in seconds using ffprobe (quiz version, robust)."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', str(mp3)],
            capture_output=True,
            text=True
        )
        data = json.loads(result.stdout)
        return float(data['format']['duration'])
    except Exception as e:
        print(f"[QUIZ VIDEO] Error getting audio duration: {str(e)}")
        return None

def create_slide_video_quiz(img: Path, mp3: Path, out_mp4: Path):
    """Create video segment from image and audio (quiz version, robust)."""
    duration = get_audio_duration_quiz(mp3)
    if duration is None or duration <= 0.1:
        print(f"[QUIZ VIDEO] Skipping segment for {img} due to missing/invalid audio duration.")
        return False
    try:
        subprocess.run([
            "ffmpeg", "-y", "-loop", "1", "-i", str(img), "-i", str(mp3),
            "-t", str(duration), "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out_mp4)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[QUIZ VIDEO] Created video segment: {out_mp4}")
        return True
    except Exception as e:
        print(f"[QUIZ VIDEO] Error creating video segment: {str(e)}")
        return False

def stitch_images_and_audio_to_video_quiz(img_dir: Path, aud_dir: Path, out_mp4: Path):
    """Stitch image and audio segments into final video (quiz version, robust)."""
    temp_dir = Path(tempfile.mkdtemp())
    try:
        img_dir, aud_dir = Path(img_dir), Path(aud_dir)
        imgs = sorted(img_dir.glob("slide_*.png"))
        mp3s = sorted(aud_dir.glob("*.mp3"))
        if not imgs:
            raise ValueError("No slide images found in the specified directory")
        if not mp3s:
            print("[QUIZ VIDEO] No audio files found. Skipping video generation.")
            return False
        pair_n = min(len(imgs), len(mp3s))
        print(f"[QUIZ VIDEO] Slides: {len(imgs)} · Audio: {len(mp3s)} (will sync to min)")
        segs = []
        for i in range(pair_n):
            seg = temp_dir / f"seg_{i+1:03d}.mp4"
            if create_slide_video_quiz(imgs[i], mp3s[i], seg):
                segs.append(seg)
            else:
                print(f"[QUIZ VIDEO] Skipped segment {i+1} (missing audio or error)")
        if not segs:
            print("[QUIZ VIDEO] No valid video segments were created.")
            return False
        concat = temp_dir / "concat.txt"
        with concat.open("w", encoding='utf-8') as f:
            for seg in segs:
                f.write(f"file '{seg.resolve()}'\n")
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
            str(out_mp4)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[QUIZ VIDEO] Final video created: {out_mp4}")
        return True
    except Exception as e:
        print(f"[QUIZ VIDEO] Error in video stitching: {str(e)}")
        return False
    finally:
        if 'temp_dir' in locals() and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
