from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text as sql_text
from datetime import datetime
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import re

from .database import get_db
from .auth import models, security

router = APIRouter(prefix="/api/videos", tags=["videos"])

# Resolve the base generated directory consistent with app.main
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT == "production"
if IS_PRODUCTION:
    _base_dir = Path("/tmp")
else:
    _base_dir = Path(__file__).resolve().parent.parent.parent
GENERATED_ROOT = (_base_dir / "generated").resolve()

def _gcs_https_from_gs(gs_url: str) -> str:
    """Convert gs://bucket/object to public HTTPS URL."""
    try:
        # gs://bucket/path/to/file -> https://storage.googleapis.com/bucket/path/to/file
        without_scheme = gs_url[len("gs://"):]
        bucket, *obj_parts = without_scheme.split("/")
        object_path = "/".join(obj_parts)
        return f"https://storage.googleapis.com/{bucket}/{object_path}"
    except Exception:
        return ""


def _gcs_prefix_from_url(url: str) -> str:
    """Given an HTTPS or gs:// URL under the assets bucket, return the object prefix directory.
    Example: https://storage.googleapis.com/assets-johnify/content/tutor/dir/lesson_video.mp4
    -> content/tutor/dir
    """
    try:
        from . import gcs_utils  # reuse bucket settings
        bucket = gcs_utils.ASSETS_BUCKET
        if url.startswith("gs://"):
            # gs://bucket/path/to/file
            without = url[len("gs://"):]
            parts = without.split("/", 1)
            if len(parts) == 2 and parts[0] == bucket:
                obj = parts[1]
            else:
                obj = parts[-1] if len(parts) else ""
        elif url.startswith("https://storage.googleapis.com/"):
            # https://storage.googleapis.com/bucket/path/to/file
            without = url[len("https://storage.googleapis.com/"):]
            parts = without.split("/", 1)
            obj = parts[1] if len(parts) == 2 else ""
        else:
            return ""
        obj = obj.strip("/")
        if not obj:
            return ""
        # Remove filename segment
        idx = obj.rfind("/")
        if idx == -1:
            return ""
        return obj[:idx]
    except Exception:
        return ""


def _delete_gcs_prefix(prefix: str) -> bool:
    """Delete all objects under the given prefix in the configured bucket. Production-only.
    Returns True on success or if nothing to delete.
    """
    try:
        from . import gcs_utils
        if not gcs_utils.IS_PRODUCTION:
            return True
        # May raise if storage not available or bucket missing
        from google.cloud import storage  # type: ignore
        client = storage.Client()
        bucket = client.bucket(gcs_utils.ASSETS_BUCKET)
        # List all blobs under prefix and delete
        to_delete = list(bucket.list_blobs(prefix=prefix))
        for blob in to_delete:
            try:
                blob.delete()
            except Exception:
                pass
        return True
    except Exception:
        return False


def _derive_thumb_url_from_video(video_url: str) -> str:
    try:
        # Replace last segment with thumbnail.jpg
        idx = video_url.rfind("/")
        if idx == -1:
            return ""
        return f"{video_url[:idx]}/thumbnail.jpg"
    except Exception:
        return ""


def get_video_files(user_id: int, db: Session) -> List[Dict[str, Any]]:
    """
    Get all video files for a specific user from the database and filesystem
    """
    print(f"Getting videos for user {user_id}")
    
    # First, get all posts for the user
    user_posts = db.query(models.UserPost).filter(
        models.UserPost.user_id == user_id,
        models.UserPost.post_path.isnot(None)  # Only include posts with a valid path
    ).order_by(models.UserPost.created_on.desc()).all()
    
    # Debug output
    print(f"Found {len(user_posts)} total posts for user {user_id}")
    for post in user_posts[:5]:  # Print first 5 posts for debugging
        print(f"Post ID: {post.post_id}, Type: {getattr(post, 'type', 'N/A')}, Path: {post.post_path}")
    
    print(f"Found {len(user_posts)} posts for user {user_id}")
    
    videos = []
    
    for post in user_posts:
        if not post.post_path:
            print(f"Skipping post {post.post_id} - no post_path")
            continue
            
        print(f"\nProcessing post {post.post_id}")
        print(f"Post path: {post.post_path}")
        print(f"Post topic: {post.post_topic}")
        
        try:
            print(f"\n--- Debugging Video Paths ---")
            print(f"Original post_path: {post.post_path}")
            print(f"Current working directory: {os.getcwd()}")

            # If post_path is a GCS path or URL, short-circuit to URLs without filesystem access
            pp = (post.post_path or "").strip()
            if pp.startswith("gs://"):
                video_url = _gcs_https_from_gs(pp)
                thumbnail_url = _derive_thumb_url_from_video(video_url)
                if video_url:
                    videos.append({
                        "id": str(post.post_id),
                        "title": post.post_topic or "Untitled Video",
                        "created_at": post.created_on.isoformat() if post.created_on else datetime.utcnow().isoformat(),
                        "video_url": video_url,
                        "thumbnail_url": thumbnail_url,
                        "type": getattr(post, "type", None),
                        "topic": post.post_topic or "",
                        "status": "completed",
                        "public": bool(getattr(post, "public", True)),
                        "tags": _normalize_post_tags(getattr(post, "tags", None)),
                    })
                    continue
            if pp.startswith("https://storage.googleapis.com/"):
                video_url = pp
                thumbnail_url = _derive_thumb_url_from_video(video_url)
                videos.append({
                    "id": str(post.post_id),
                    "title": post.post_topic or "Untitled Video",
                    "created_at": post.created_on.isoformat() if post.created_on else datetime.utcnow().isoformat(),
                    "video_url": video_url,
                    "thumbnail_url": thumbnail_url,
                    "type": getattr(post, "type", None),
                    "topic": post.post_topic or "",
                    "status": "completed",
                    "public": bool(getattr(post, "public", True)),
                    "tags": _normalize_post_tags(getattr(post, "tags", None)),
                })
                continue

            # Back-compat: if post_path was stored as a served URL under /videos,
            # convert to a generated-relative path for local resolution
            if pp.startswith("/videos/"):
                # '/videos/dir/file.mp4' -> 'dir/file.mp4' under generated root
                pp = pp[len("/videos/"):]
                # Keep pp without leading slashes
                pp = pp.lstrip('/')

            # The post_path contains both directory and filename, e.g.:
            # 'generated/learn_why_are_women_not_safe_in_india_and_mexico_1753718382\learn_why_are_women_not_safe_in_india_and_mexico_1753718382.mp4'
            
            # Normalize the path and force it to be relative under generated/
            normalized_path = (pp or '').replace('\\', '/').strip()
            if 'generated/' in normalized_path:
                # Trim everything before the first occurrence of generated/
                idx = normalized_path.find('generated/')
                normalized_path = normalized_path[idx:]
            
            # Remove 'generated/' prefix if it exists
            if normalized_path.startswith('generated/'):
                normalized_path = normalized_path[10:]
                
            # Split into directory and filename (post_path may be a directory)
            path_parts = normalized_path.split('/') if normalized_path else []
            last_part = path_parts[-1] if path_parts else ''
            if last_part.lower().endswith('.mp4'):
                # post_path points to a specific file; scan its parent directory
                directory_name = '/'.join(path_parts[:-1])
                video_filename = last_part
            else:
                # post_path points to a directory; scan that directory directly
                directory_name = '/'.join(path_parts)
                video_filename = None
            
            # Construct the full path to the video directory under the resolved generated root
            video_dir_path = os.path.join(str(GENERATED_ROOT), directory_name)
            video_dir_path = os.path.normpath(video_dir_path)  # Normalize the path for the current OS
            
            print(f"Normalized video directory path: {video_dir_path}")
            print(f"Directory exists: {os.path.exists(video_dir_path)}")
            
            # Find the actual video file in the directory (handles cases where filename might have newlines or spaces)
            video_filename = None
            video_path = None
            
            if os.path.exists(video_dir_path):
                print(f"Directory contents: {os.listdir(video_dir_path)}")
                # Look for .mp4 files in the directory
                for file in os.listdir(video_dir_path):
                    if file.endswith('.mp4'):
                        video_filename = file
                        video_path = os.path.join(video_dir_path, video_filename)
                        video_path = os.path.normpath(video_path)  # Normalize the path
                        break
            
            video_abs_path = os.path.abspath(video_path) if video_path else ""
            
            print(f"Directory name: {directory_name}")
            print(f"Found video file: {video_filename}" if video_filename else "No video file found")
            print(f"Video directory path: {video_dir_path}")
            print(f"Video path: {video_path}" if video_path else "No video path")
            print(f"Absolute video path: {video_abs_path}" if video_abs_path else "No absolute path")
            print(f"Directory exists: {os.path.exists(video_dir_path) if os.path.exists(video_dir_path) else False}")
            print(f"File exists: {os.path.exists(video_path) if video_path else False}")
            
            # Check if the video file exists
            if video_path and os.path.exists(video_path):
                print(f"✅ Video found at: {video_path}")
                
                # Generate thumbnail path (assuming it's in the same directory with .jpg extension)
                thumbnail_filename = "thumbnail.jpg"
                thumbnail_path = os.path.join(video_dir_path, thumbnail_filename)
                
                # Generate URL for the video file using the /videos/ endpoint
                # Get the base URL from environment or use a default
                base_url = os.getenv("BACKEND_URL", "http://localhost:8000")

                # Build clean relative path under /videos without any '..' components
                # directory_name is already relative to the generated/ folder
                # video_filename was discovered from the filesystem
                safe_dir = (directory_name or "").replace('\\', '/').strip('/')
                safe_file = (video_filename or "").replace('\\', '/').strip('/')
                rel_path = f"{safe_dir}/{safe_file}" if safe_dir else safe_file
                rel_path = rel_path.lstrip('/')
                video_url = f"{base_url}/videos/{rel_path}"

                # Generate thumbnail URL if it exists (thumbnail.jpg inside the same directory)
                thumbnail_url = ""
                if os.path.exists(thumbnail_path):
                    thumb_rel_path = f"{safe_dir}/thumbnail.jpg" if safe_dir else "thumbnail.jpg"
                    thumb_rel_path = thumb_rel_path.replace('\\', '/').lstrip('/')
                    thumbnail_url = f"{base_url}/videos/{thumb_rel_path}"
                
                print(f"Generated video URL: {video_url}")
                print(f"Generated thumbnail URL: {thumbnail_url}")
                print(f"Video path: {video_path}")
                
                videos.append({
                    "id": str(post.post_id),
                    "title": post.post_topic or "Untitled Video",
                    "created_at": post.created_on.isoformat() if post.created_on else datetime.utcnow().isoformat(),
                    "video_url": video_url,
                    "thumbnail_url": thumbnail_url,
                    "type": getattr(post, "type", None),
                    "topic": post.post_topic or "",
                    "status": "completed",
                    "public": bool(getattr(post, "public", True)),
                    "tags": _normalize_post_tags(getattr(post, "tags", None)),
                })
            else:
                print(f"❌ Video not found at: {video_path}")
                if video_dir_path and os.path.exists(video_dir_path):
                    print(f"Directory contents: {os.listdir(video_dir_path)}")
                else:
                    print(f"Directory does not exist: {video_dir_path}")
        except Exception as e:
            import traceback
            print(f"❌ Error processing video: {str(e)}")
            print(f"Traceback: {traceback.format_exc()}")
            raise  # Re-raise the exception to see it in the API response
    
    return videos

@router.get("/my-videos", response_model=List[Dict[str, Any]])
async def get_my_videos(
    current_user: models.User = Depends(security.get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get all videos for the currently authenticated user
    """
    try:
        return get_video_files(current_user.user_id, db)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching videos: {str(e)}"
        )


@router.delete("/{post_id}")
async def delete_video_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(security.get_current_active_user),
):
    """Delete a user's video post and associated storage (GCS in production)."""
    try:
        post = db.query(models.UserPost).filter(models.UserPost.post_id == post_id).first()
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
        if getattr(post, "user_id", None) != getattr(current_user, "user_id", None):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this post")

        # Delete dependent likes first to satisfy FK constraints (public.user_posts_likes.post_id -> user_posts.post_id)
        try:
            db.execute(sql_text(
                """
                DELETE FROM public.user_posts_likes
                WHERE post_id = :post_id
                """
            ), {"post_id": post_id})
        except Exception:
            # Do not fail the entire operation on likes cleanup issues; rollback handled below if needed
            pass

        # Attempt to delete storage assets
        pp = (post.post_path or "").strip()
        deleted_storage = True
        try:
            if pp.startswith("gs://") or pp.startswith("https://storage.googleapis.com/"):
                prefix = _gcs_prefix_from_url(pp)
                if prefix:
                    deleted_storage = _delete_gcs_prefix(prefix)
            elif pp.startswith("generated/"):
                # Dev/local cleanup: remove local directory
                try:
                    # Normalize to generated root
                    directory = pp.replace("\\", "/").split("generated/", 1)[-1]
                    base = str(GENERATED_ROOT)
                    full_dir = os.path.normpath(os.path.join(base, directory))
                    if os.path.isdir(full_dir):
                        import shutil
                        shutil.rmtree(full_dir, ignore_errors=True)
                except Exception:
                    pass
        except Exception:
            deleted_storage = False

        # Delete DB row (post) after removing likes
        db.delete(post)
        db.commit()
        return {"id": str(post_id), "deleted": True, "storage_deleted": bool(deleted_storage)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete post: {str(e)}")

# New: Public feed endpoint aggregating videos from all users

class VisibilityUpdate(BaseModel):
    public: bool

@router.patch("/{post_id}/visibility")
async def update_post_visibility(
    post_id: int,
    payload: VisibilityUpdate,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(security.get_current_active_user),
):
    try:
        post = db.query(models.UserPost).filter(models.UserPost.post_id == post_id).first()
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
        if getattr(post, "user_id", None) != getattr(current_user, "user_id", None):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to modify this post")
        # Update visibility
        setattr(post, "public", bool(payload.public))
        db.add(post)
        db.commit()
        db.refresh(post)
        return {"id": str(post.post_id), "public": bool(getattr(post, "public", True))}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update visibility: {str(e)}")

# --- Likes endpoints ---
class LikeRequest(BaseModel):
    action: Optional[str] = None  # e.g., 'like' (optional)

@router.get("/{post_id}/likes")
async def get_post_likes(
    post_id: int,
    db: Session = Depends(get_db),
):
    """Return the like count for a post. Defaults to 0 when no row exists."""
    try:
        # Use raw SQL to avoid requiring a SQLAlchemy model for the likes table
        row = db.execute(sql_text(
            """
            SELECT likes_count
            FROM public.user_posts_likes
            WHERE post_id = :post_id
            """
        ), {"post_id": post_id}).fetchone()
        count = int(row[0]) if row and row[0] is not None else 0
        return {"likes_count": count}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to fetch likes: {str(e)}")

@router.post("/{post_id}/likes")
async def like_post(
    post_id: int,
    payload: LikeRequest,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(security.get_current_active_user),
):
    """Increment like count for a post.
    Rules:
    - Must be authenticated.
    - Cannot like your own post.
    """
    try:
        # Validate post exists
        post = db.query(models.UserPost).filter(models.UserPost.post_id == post_id).first()
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
        # Prevent liking own video
        if getattr(post, "user_id", None) == getattr(current_user, "user_id", None):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot like your own post")

        # Upsert-like logic: insert row if absent, otherwise increment
        # 1) Try update
        updated = db.execute(sql_text(
            """
            UPDATE public.user_posts_likes
            SET likes_count = COALESCE(likes_count, 0) + 1,
                updated_on = NOW()
            WHERE post_id = :post_id
            RETURNING likes_count
            """
        ), {"post_id": post_id}).fetchone()

        new_count: Optional[int] = None
        if updated and len(updated) > 0:
            new_count = int(updated[0])
        else:
            # 2) No row existed; insert with 1
            inserted = db.execute(sql_text(
                """
                INSERT INTO public.user_posts_likes (post_id, likes_count, updated_on)
                VALUES (:post_id, 1, NOW())
                RETURNING likes_count
                """
            ), {"post_id": post_id}).fetchone()
            new_count = int(inserted[0]) if inserted and len(inserted) > 0 else 1

        db.commit()
        return {"likes_count": new_count}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to like post: {str(e)}")
def _collect_videos_for_post(post: models.UserPost) -> Dict[str, Any]:
    import os
    from datetime import datetime
    
    try:
        # Get and validate post path
        pp = (post.post_path or "").strip()
        if not pp:
            print(f"No post_path for post {post.post_id}")
            return {}
        
        # If post_path is already a cloud URL, return directly without filesystem checks
        if pp.startswith("gs://"):
            video_url = _gcs_https_from_gs(pp)
            thumbnail_url = _derive_thumb_url_from_video(video_url)
            if video_url:
                return {
                    "id": str(post.post_id),
                    "title": post.post_topic or "Untitled Video",
                    "created_at": post.created_on.isoformat() if post.created_on else datetime.utcnow().isoformat(),
                    "video_url": video_url,
                    "thumbnail_url": thumbnail_url,
                    "topic": post.post_topic or "",
                    "status": "completed",
                    "user_id": post.user_id,
                    "user_name": getattr(post, "user", None) and getattr(post.user, "user_name", None),
                    "tags": _normalize_post_tags(getattr(post, "tags", None)),
                }
        if pp.startswith("https://storage.googleapis.com/"):
            video_url = pp
            thumbnail_url = _derive_thumb_url_from_video(video_url)
            return {
                "id": str(post.post_id),
                "title": post.post_topic or "Untitled Video",
                "created_at": post.created_on.isoformat() if post.created_on else datetime.utcnow().isoformat(),
                "video_url": video_url,
                "thumbnail_url": thumbnail_url,
                "topic": post.post_topic or "",
                "status": "completed",
                "user_id": post.user_id,
                "user_name": getattr(post, "user", None) and getattr(post.user, "user_name", None),
                "tags": _normalize_post_tags(getattr(post, "tags", None)),
            }
        
        # Normalize path (handle both Windows and Unix paths)
        normalized_path = pp.replace('\\', '/').strip()
        
        # Handle different path formats
        if normalized_path.startswith("generated/"):
            # Remove 'generated/' prefix if present
            normalized_path = normalized_path[10:]
        elif '/generated/' in normalized_path:
            # Extract path after 'generated/'
            idx = normalized_path.find('/generated/') + 11
            normalized_path = normalized_path[idx:]
            
        # Extract directory and filename
        path_parts = [p for p in normalized_path.split('/') if p]
        if not path_parts:
            print(f"Invalid path format: {pp}")
            return {}
            
        # Check if last part is an MP4 file
        if path_parts[-1].lower().endswith('.mp4'):
            directory_name = '/'.join(path_parts[:-1])
            video_filename = path_parts[-1]
        else:
            directory_name = '/'.join(path_parts)
            video_filename = None
            
        # Build full directory path
        video_dir_path = os.path.normpath(os.path.join(str(GENERATED_ROOT), directory_name))
        
        # Find video file if not already determined
        if not video_filename and os.path.exists(video_dir_path):
            for file in os.listdir(video_dir_path):
                if file.lower().endswith('.mp4'):
                    video_filename = file
                    break
                    
        if not video_filename:
            print(f"No MP4 file found in {video_dir_path}")
            return {}
            
        video_path = os.path.join(video_dir_path, video_filename)
        if not os.path.exists(video_path):
            print(f"Video file not found: {video_path}")
            return {}
            
        # Build URLs
        base_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip('/')
        rel_path = f"{directory_name}/{video_filename}" if directory_name else video_filename
        rel_path = rel_path.replace('\\', '/').lstrip('/')
        video_url = f"{base_url}/videos/{rel_path}"

        # Handle thumbnail
        thumbnail_url = ""
        thumb_path = os.path.join(video_dir_path, "thumbnail.jpg")
        if not os.path.exists(thumb_path):
            # Try to find any jpg/png thumbnail
            for ext in ['.jpg', '.jpeg', '.png']:
                for file in os.listdir(video_dir_path):
                    if file.lower().endswith(ext):
                        thumb_path = os.path.join(video_dir_path, file)
                        break
                        
        if os.path.exists(thumb_path):
            thumb_rel = os.path.relpath(thumb_path, GENERATED_ROOT).replace('\\', '/')
            thumbnail_url = f"{base_url}/videos/{thumb_rel}"
            
        return {
            "id": str(post.post_id),
            "title": post.post_topic or "Untitled Video",
            "created_at": post.created_on.isoformat() if post.created_on else datetime.utcnow().isoformat(),
            "video_url": video_url,
            "thumbnail_url": thumbnail_url,
            "topic": post.post_topic or "",
            "status": "completed",
            "user_id": post.user_id,
            "user_name": getattr(post.user, "user_name", None) if getattr(post, "user", None) is not None else None,
            "tags": getattr(post, "tags", None) or [],
        }
    except Exception as e:
        print(f"Error processing post {getattr(post, 'post_id', 'unknown')}: {str(e)}")
        return {}

# --- Tag helpers for Learn feed ---
def _sanitize_tags(tags: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for t in tags:
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

def _generate_tags_for_topic(topic: str) -> List[str]:
    """Best-effort tag generation using DeepSeek if available; fallback to simple keywords.
    Retries DeepSeek a few times before falling back.
    """
    topic = (topic or "").strip()
    if not topic:
        return []
    # Try DeepSeek via slidegen client with light retries
    try:
        from . import slidegen  # type: ignore
        client = slidegen.get_deepseek_client()
        if client:
            import time
            import json, re
            prompt = (
                "Generate exactly 7 single-word, lowercase tags for the topic: '" + topic +
                "'. Tags should be generic, recognizable keywords (e.g., genre, subject, entity). Return ONLY a JSON array of strings."
            )
            attempts = 0
            while attempts < 3:
                attempts += 1
                try:
                    print(f"[learn-feed] deepseek_attempt={attempts} topic='{topic}'")
                    resp = client.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": "You generate only JSON arrays of tags."},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.2,
                        max_tokens=256,
                    )
                    text = ""
                    try:
                        text = (resp.choices[0].message.content or "").strip()
                    except Exception:
                        text = str(resp)
                    arr = None
                    try:
                        arr = json.loads(text)
                    except Exception:
                        m = re.search(r"\[[\s\S]*\]", text)
                        if m:
                            try:
                                arr = json.loads(m.group(0))
                            except Exception:
                                arr = None
                    if isinstance(arr, list) and len(arr) > 0:
                        tags = _sanitize_tags([str(x) for x in arr])
                        if tags:
                            print(f"[learn-feed] deepseek_success attempts={attempts} tags={tags}")
                            return tags
                except Exception as e:
                    print(f"[learn-feed] deepseek_error attempt={attempts} err={e}")
                # brief backoff
                time.sleep(1.0)
    except Exception as e:
        print(f"[learn-feed] deepseek_client_unavailable err={e}")
    # Fallback: simple keywords from topic
    import re
    words = re.findall(r"[A-Za-z][A-Za-z\-]{1,}\b", topic.lower())
    # Prioritize unique meaningful words
    uniq: List[str] = []
    for w in words:
        if w not in uniq:
            uniq.append(w)
    tags = _sanitize_tags(uniq)
    print(f"[learn-feed] deepseek_fallback tags={tags}")
    return tags

def _normalize_post_tags(raw: Any) -> List[str]:
    """Normalize tags from DB which may be stored as list, CSV string, or JSON string.
    Returns a sanitized list of single-word lowercase tags (using _sanitize_tags).
    """
    try:
        vals: List[str] = []
        if raw is None:
            return []
        if isinstance(raw, list):
            vals = [str(x) for x in raw]
        elif isinstance(raw, str):
            s = raw.strip()
            # Try JSON array first
            if (s.startswith('[') and s.endswith(']')) or (s.startswith('"') and s.endswith('"')):
                try:
                    import json as _json
                    parsed = _json.loads(s)
                    if isinstance(parsed, list):
                        vals = [str(x) for x in parsed]
                    elif isinstance(parsed, str):
                        # Single string inside quotes
                        vals = [p.strip() for p in parsed.split(',') if p.strip()]
                    else:
                        vals = [s]
                except Exception:
                    # Fallback to CSV split
                    vals = [p.strip() for p in s.split(',') if p.strip()]
            else:
                # CSV
                vals = [p.strip() for p in s.split(',') if p.strip()]
        else:
            # Unknown type -> string then CSV split on commas
            s = str(raw)
            vals = [p.strip() for p in s.replace('\n', ' ').replace('\t', ' ').split(',') if p.strip()]
        return _sanitize_tags([v.lower() for v in vals])
    except Exception:
        return []

@router.get("/feed", response_model=List[Dict[str, Any]])
async def get_feed_videos(
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(security.get_current_user_optional),
):
    """
    Public feed of videos across all users.
    """
    try:
        posts = (
            db.query(models.UserPost)
            .options(joinedload(models.UserPost.user))
            .filter(models.UserPost.post_path != None)
            .filter(models.UserPost.public == True)
            .order_by(models.UserPost.created_on.desc())
            .limit(200)
            .all()
        )
        out: List[Dict[str, Any]] = []
        for post in posts:
            # Exclude current user's own posts if authenticated
            try:
                if current_user is not None and getattr(current_user, "user_id", None) == getattr(post, "user_id", None):
                    continue
            except Exception:
                pass
            # Prefer direct GCS URLs when present
            pp = (post.post_path or "").strip()
            if pp.startswith("gs://"):
                video_url = _gcs_https_from_gs(pp)
                thumbnail_url = _derive_thumb_url_from_video(video_url)
                if video_url:
                    out.append({
                        "id": str(post.post_id),
                        "title": post.post_topic or "Untitled Video",
                        "created_at": post.created_on.isoformat() if post.created_on else datetime.utcnow().isoformat(),
                        "video_url": video_url,
                        "thumbnail_url": thumbnail_url,
                        "topic": post.post_topic or "",
                        "status": "completed",
                        "user_id": post.user_id,
                        "user_name": getattr(post, "user", None) and getattr(post.user, "user_name", None),
                        "tags": getattr(post, "tags", None) or [],
                    })
                    continue
            if pp.startswith("https://storage.googleapis.com/"):
                video_url = pp
                thumbnail_url = _derive_thumb_url_from_video(video_url)
                out.append({
                    "id": str(post.post_id),
                    "title": post.post_topic or "Untitled Video",
                    "created_at": post.created_on.isoformat() if post.created_on else datetime.utcnow().isoformat(),
                    "video_url": video_url,
                    "thumbnail_url": thumbnail_url,
                    "topic": post.post_topic or "",
                    "status": "completed",
                    "user_id": post.user_id,
                    "user_name": getattr(post, "user", None) and getattr(post.user, "user_name", None),
                    "tags": getattr(post, "tags", None) or [],
                })
                continue

            item = _collect_videos_for_post(post)
            if item.get("video_url"):
                out.append(item)
        return out
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching feed videos: {str(e)}"
        )

@router.get("/learn-feed")
async def get_learn_feed(
    topic: str = Query("", description="Topic to derive tags for related videos (DeepSeek-generated)"),
    tags: Optional[str] = Query(None, description="Optional precomputed DeepSeek tags (CSV or JSON array)"),
    limit_similar: int = Query(12, ge=0, le=100),
    limit_others: int = Query(12, ge=0, le=100),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(security.get_current_user_optional),
):
    """Return two sections of public videos: similar (by tag overlap with topic) and others.
    Excludes the current user's posts when authenticated. Results sorted by recency.
    """
    try:
        # If precomputed tags were provided (from generate-tags endpoint), use them
        qtags: List[str] = []
        tag_source = ""
        if tags:
            raw: List[str] = []
            try:
                import json as _json
                parsed = _json.loads(tags)
                if isinstance(parsed, list):
                    raw = [str(x) for x in parsed]
            except Exception:
                raw = [p.strip() for p in tags.split(',') if p.strip()]
            qtags = _sanitize_tags([s.lower() for s in raw])
            tag_source = "deepseek(precomputed)"
            print(f"[learn-feed] using_precomputed_tags: {qtags}")
        else:
            # Always generate tags from topic via DeepSeek (with fallback)
            qtags = _sanitize_tags(_generate_tags_for_topic(topic.lower())) if topic else []
            tag_source = "deepseek" if qtags and not set(qtags).issubset(set(topic.lower().split())) else "fallback"
            print(f"[learn-feed] generated_tags topic='{topic}' source={tag_source}: {qtags}")
        qset = set(qtags)

        # Get base query for public posts
        query = (
            db.query(models.UserPost)
            .options(joinedload(models.UserPost.user))
            .filter(models.UserPost.post_path != None)
            .filter(models.UserPost.public == True)
        )

        # Exclude current user's own posts if authenticated
        if current_user is not None:
            query = query.filter(models.UserPost.user_id != current_user.user_id)

        # Get all matching posts
        all_posts = query.order_by(models.UserPost.created_on.desc()).limit(300).all()
        print(f"Found {len(all_posts)} public posts")

        similar_items = []
        other_items = []

        for post in all_posts:
            # Get video details
            item = _collect_videos_for_post(post)
            if not item or not item.get("video_url"):
                continue

            # Get post tags (normalize CSV/JSON/list to sanitized words)
            post_tags = _normalize_post_tags(getattr(post, "tags", None))
            
            # Check for tag matches via set intersection
            has_match = bool(qset.intersection(set(post_tags))) if qset else False
            
            if has_match and len(similar_items) < limit_similar:
                try:
                    print(f"[learn-feed] match post_id={post.post_id} post_tags={post_tags} qtags={qtags}")
                except Exception:
                    pass
                similar_items.append(item)
            elif len(other_items) < limit_others:
                try:
                    if not has_match:
                        print(f"[learn-feed] no_match post_id={post.post_id} post_tags={post_tags} qtags={qtags}")
                except Exception:
                    pass
                other_items.append(item)

            # Early exit if we have enough items
            if len(similar_items) >= limit_similar and len(other_items) >= limit_others:
                break

        # Fallback: if no similar by tags, try loose title keyword match
        if len(similar_items) == 0 and qset:
            try:
                print("[learn-feed] no tag matches; applying title-keyword fallback")
                # Build a small synonym set for broader matching
                synonyms = set()
                if any(t in qset for t in ["car", "cars", "automotive", "supercar", "supercars"]):
                    synonyms.update(["car", "cars", "automotive", "vehicle", "vehicles", "supercar", "supercars", "hypercar", "hypercars", "speed", "fast"])
                # Tokenize qtags and synonyms
                qwords = set()
                for t in list(qset) + list(synonyms):
                    for w in re.findall(r"[a-z]{3,}", str(t)):
                        qwords.add(w)
                # Scan posts again in order
                for post in all_posts:
                    if len(similar_items) >= limit_similar:
                        break
                    title = (post.post_topic or "").lower()
                    if not title:
                        continue
                    # simple contains check for any keyword
                    hit = any(w in title for w in qwords)
                    if hit:
                        item = _collect_videos_for_post(post)
                        if item and item.get("video_url"):
                            similar_items.append(item)
                print(f"[learn-feed] fallback_title_matches added={len(similar_items)}")
            except Exception as e:
                print(f"[learn-feed] fallback_title_error err={e}")

        print(f"[learn-feed] returning similar={len(similar_items)} other={len(other_items)}")
        # Return both snake_case and camelCase for compatibility with existing frontend
        return {
            "similar": similar_items,
            "others": other_items,
            "similarItems": similar_items,
            "otherItems": other_items,
            "query_tags": qtags,
            "queryTags": qtags,
            "tag_source": tag_source,
        }
    except Exception as e:
        import traceback
        print(f"Error in get_learn_feed: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching learn feed: {str(e)}",
        )

@router.get("/generate-tags")
async def generate_tags(
    topic: str = Query("", description="Topic to generate tags via DeepSeek"),
):
    try:
        if not topic.strip():
            raise HTTPException(status_code=400, detail="Missing topic")
        tags = _sanitize_tags(_generate_tags_for_topic(topic.strip().lower()))
        # Heuristic: if tags are subset of topic words, mark fallback
        source = "deepseek" if tags and not set(tags).issubset(set(topic.lower().split())) else "fallback"
        print(f"[generate-tags] topic='{topic}' source={source} tags={tags}")
        return {"tags": tags, "source": source}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[generate-tags] error: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to generate tags: {str(e)}")
