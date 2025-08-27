from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text as sql_text
from datetime import datetime
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

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
    
    # Get all posts for the user
    user_posts = db.query(models.UserPost).filter(
        models.UserPost.user_id == user_id
    ).order_by(models.UserPost.created_on.desc()).all()
    
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
                        "topic": post.post_topic or "",
                        "status": "completed",
                        "public": bool(getattr(post, "public", True)),
                        "tags": getattr(post, "tags", None) or [],
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
                    "topic": post.post_topic or "",
                    "status": "completed",
                    "public": bool(getattr(post, "public", True)),
                    "tags": getattr(post, "tags", None) or [],
                })
                continue

            # The post_path contains both directory and filename, e.g.:
            # 'generated/learn_why_are_women_not_safe_in_india_and_mexico_1753718382\learn_why_are_women_not_safe_in_india_and_mexico_1753718382.mp4'
            
            # Normalize the path and force it to be relative under generated/
            normalized_path = (post.post_path or '').replace('\\', '/').strip()
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
                    "topic": post.post_topic or "",
                    "status": "completed",
                    "public": bool(getattr(post, "public", True)),
                    "tags": getattr(post, "tags", None) or [],
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

        # Delete DB row
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
    # Normalize and locate video file within generated/<dir>
    normalized_path = (post.post_path or "").replace('\\', '/').strip()
    if 'generated/' in normalized_path:
        # Keep only path from generated/
        idx = normalized_path.find('generated/')
        normalized_path = normalized_path[idx+len('generated/'):]
    elif normalized_path.startswith('generated/'):
        normalized_path = normalized_path[10:]
    path_parts = normalized_path.split('/') if normalized_path else []
    last_part = path_parts[-1] if path_parts else ''
    if last_part.lower().endswith('.mp4'):
        directory_name = '/'.join(path_parts[:-1])
    else:
        directory_name = '/'.join(path_parts)
    video_dir_path = os.path.normpath(os.path.join(str(GENERATED_ROOT), directory_name))

    video_filename = None
    video_path = None
    if os.path.exists(video_dir_path):
        for file in os.listdir(video_dir_path):
            if file.endswith('.mp4'):
                video_filename = file
                video_path = os.path.normpath(os.path.join(video_dir_path, video_filename))
                break

    if not (video_path and os.path.exists(video_path)):
        return {}

    # Build URLs
    base_url = os.getenv("BACKEND_URL", "http://localhost:8000")
    safe_dir = (directory_name or "").replace('\\', '/').strip('/')
    safe_file = (video_filename or "").replace('\\', '/').strip('/')
    rel_path = f"{safe_dir}/{safe_file}" if safe_dir else safe_file
    rel_path = rel_path.lstrip('/')
    video_url = f"{base_url}/videos/{rel_path}"

    # Thumbnail
    thumbnail_url = ""
    thumb_path = os.path.join(video_dir_path, "thumbnail.jpg")
    if os.path.exists(thumb_path):
        thumb_rel = f"{safe_dir}/thumbnail.jpg" if safe_dir else "thumbnail.jpg"
        thumb_rel_clean = thumb_rel.replace('\\', '/').lstrip('/')
        thumbnail_url = f"{base_url}/videos/{thumb_rel_clean}"

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
