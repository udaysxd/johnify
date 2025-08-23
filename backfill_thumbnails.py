import os
import subprocess
from pathlib import Path
from PIL import Image

TARGET_SIZE = (1280, 720)

ROOT = Path(__file__).parent
GENERATED_DIR = ROOT / "generated"


def letterbox_to_jpeg(src_png: Path, out_jpg: Path):
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src_png) as im:
        im = im.convert("RGB")
        tw, th = TARGET_SIZE
        im_ratio = im.width / im.height
        tgt_ratio = tw / th
        if im_ratio > tgt_ratio:
            new_w = tw
            new_h = int(tw / im_ratio)
        else:
            new_h = th
            new_w = int(th * im_ratio)
        im_resized = im.resize((new_w, new_h))
        canvas = Image.new("RGB", (tw, th), color=(20, 32, 48))
        x = (tw - new_w) // 2
        y = (th - new_h) // 2
        canvas.paste(im_resized, (x, y))
        canvas.save(out_jpg, format="JPEG", quality=85)


def try_extract_frame_with_ffmpeg(video_path: Path, out_jpg: Path) -> bool:
    try:
        # Extract a frame at 1s
        cmd = [
            "ffmpeg", "-y",
            "-ss", "1",
            "-i", str(video_path),
            "-frames:v", "1",
            str(out_jpg),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return res.returncode == 0 and out_jpg.exists() and out_jpg.stat().st_size > 1024
    except Exception:
        return False


def find_first_slide_png(dir_path: Path) -> Path | None:
    # Common patterns: images/slide_*.png or slide_*.png
    slides = sorted(dir_path.glob("slide_*.png"))
    if slides:
        return slides[0]
    images_dir = dir_path / "images"
    if images_dir.exists() and images_dir.is_dir():
        slides = sorted(images_dir.glob("slide_*.png"))
        if slides:
            return slides[0]
    # Other common Marp outputs
    for pat in [
        "*.png",
        "images.[0-9][0-9][0-9].png",
        "images.[0-9][0-9][0-9]",
        "[0-9][0-9][0-9].png",
    ]:
        cand = sorted(dir_path.glob(pat))
        for p in cand:
            try:
                if p.is_file() and p.stat().st_size > 1024:
                    return p
            except Exception:
                pass
    return None


def backfill():
    if not GENERATED_DIR.exists():
        print(f"No generated directory at {GENERATED_DIR}")
        return

    total = 0
    created = 0
    for sub in sorted(GENERATED_DIR.iterdir()):
        if not sub.is_dir():
            continue
        total += 1
        thumb = sub / "thumbnail.jpg"
        if thumb.exists() and thumb.stat().st_size > 1024:
            print(f"✓ Exists: {thumb}")
            continue

        # find a video mp4 in dir
        mp4 = None
        for f in sub.iterdir():
            if f.is_file() and f.suffix.lower() == ".mp4":
                mp4 = f
                break

        # prefer creating from slide image for consistency
        slide_png = find_first_slide_png(sub)
        if slide_png:
            try:
                letterbox_to_jpeg(slide_png, thumb)
                print(f"+ Created from slide: {thumb}")
                created += 1
                continue
            except Exception as e:
                print(f"! Failed from slide {slide_png}: {e}")

        # fallback: extract a frame from video
        if mp4 and try_extract_frame_with_ffmpeg(mp4, thumb):
            print(f"+ Created from video frame: {thumb}")
            created += 1
            continue

        print(f"- Skipped (no sources): {sub}")

    print(f"Done. Scanned {total} dirs, created {created} thumbnails.")


if __name__ == "__main__":
    backfill()
