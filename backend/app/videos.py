from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
import os
from typing import List, Dict, Any

from .database import get_db
from .auth import models, security

router = APIRouter(prefix="/api/videos", tags=["videos"])

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
                
            # Split into directory and filename
            path_parts = normalized_path.split('/')
            
            # The directory is everything except the last part (filename)
            directory_name = '/'.join(path_parts[:-1])
            video_filename = path_parts[-1] if path_parts[-1].endswith('.mp4') else None
            
            # Construct the full path to the video directory
            video_dir_path = os.path.join("generated", directory_name)
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
                    "status": "completed"
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

# New: Public feed endpoint aggregating videos from all users
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
    directory_name = '/'.join(path_parts[:-1]) if path_parts else ''
    video_dir_path = os.path.normpath(os.path.join("generated", directory_name))

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
    }

@router.get("/feed", response_model=List[Dict[str, Any]])
async def get_feed_videos(
    db: Session = Depends(get_db)
):
    """
    Public feed of videos across all users.
    """
    try:
        posts = (
            db.query(models.UserPost)
            .options(joinedload(models.UserPost.user))
            .filter(models.UserPost.post_path != None)
            .order_by(models.UserPost.created_on.desc())
            .limit(200)
            .all()
        )
        out: List[Dict[str, Any]] = []
        for post in posts:
            item = _collect_videos_for_post(post)
            if item.get("video_url"):
                out.append(item)
        return out
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching feed videos: {str(e)}"
        )
