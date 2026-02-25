from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
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

# ===== Saved/Bookmarks =====
def _ensure_saved_posts_table(db: Session) -> None:
    """Create saved_posts table if it does not exist.

    Schema:
      public.saved_posts (
        user_id BIGINT NOT NULL REFERENCES public.users(user_id) ON DELETE CASCADE,
        post_id BIGINT NOT NULL REFERENCES public.user_posts(post_id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (user_id, post_id)
      )
    """
    try:
        db.execute(sql_text(
            """
            CREATE TABLE IF NOT EXISTS public.saved_posts (
                user_id BIGINT NOT NULL REFERENCES public.users(user_id) ON DELETE CASCADE,
                post_id BIGINT NOT NULL REFERENCES public.user_posts(post_id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, post_id)
            );
            """
        ))
        # Helpful index to list a user's saved items by recency
        db.execute(sql_text(
            """
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='idx_saved_posts_user_created'
                ) THEN
                    CREATE INDEX idx_saved_posts_user_created ON public.saved_posts (user_id, created_at DESC);
                END IF;
            END $$;
            """
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise

@router.put("/{post_id}/save")
async def save_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(security.get_current_active_user),
):
    """Save (bookmark) a post for the current user. Idempotent."""
    try:
        _ensure_saved_posts_table(db)
        # Validate post exists
        post = db.query(models.UserPost).filter(models.UserPost.post_id == post_id).first()
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

        db.execute(sql_text(
            """
            INSERT INTO public.saved_posts (user_id, post_id, created_at)
            VALUES (:uid, :pid, NOW())
            ON CONFLICT (user_id, post_id) DO NOTHING
            """
        ), {"uid": int(current_user.user_id), "pid": int(post_id)})
        db.commit()
        return {"post_id": int(post_id), "saved": True}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to save post: {str(e)}")

@router.delete("/{post_id}/save")
async def unsave_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(security.get_current_active_user),
):
    """Unsave (remove bookmark). Idempotent delete."""
    try:
        _ensure_saved_posts_table(db)
        db.execute(sql_text(
            """
            DELETE FROM public.saved_posts WHERE user_id = :uid AND post_id = :pid
            """
        ), {"uid": int(current_user.user_id), "pid": int(post_id)})
        db.commit()
        return {"post_id": int(post_id), "saved": False}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to unsave post: {str(e)}")

@router.get("/saved/status")
async def saved_status(
    ids: Optional[str] = Query(None, description="Comma-separated list of post IDs"),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(security.get_current_user_optional),
):
    """Return which of the given post IDs are saved by the current user.

    Response: { saved: [post_id, ...] }
    """
    try:
        _ensure_saved_posts_table(db)
        if not current_user:
            return {"saved": []}
        raw = (ids or "").strip()
        if not raw:
            return {"saved": []}
        try:
            post_ids = [int(x) for x in re.split(r"[\s,]+", raw) if x.strip()]
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ids parameter")
        if not post_ids:
            return {"saved": []}
        rows = db.execute(sql_text(
            """
            SELECT post_id FROM public.saved_posts
            WHERE user_id = :uid AND post_id = ANY(:pids)
            """
        ), {"uid": int(current_user.user_id), "pids": post_ids}).fetchall()
        out = []
        for r in rows or []:
            try:
                out.append(int(r[0]))
            except Exception:
                pass
        return {"saved": out}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to fetch saved status: {str(e)}")

@router.get("/saved", response_model=List[Dict[str, Any]])
async def list_my_saved(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(security.get_current_active_user),
):
    """Return the current user's saved videos ordered by when they were saved."""
    try:
        _ensure_saved_posts_table(db)
        rows = db.execute(sql_text(
            """
            SELECT sp.post_id
            FROM public.saved_posts sp
            WHERE sp.user_id = :uid
            ORDER BY sp.created_at DESC
            LIMIT 300
            """
        ), {"uid": int(current_user.user_id)}).fetchall()
        post_ids = [int(r[0]) for r in rows or []]
        if not post_ids:
            return []
        # Fetch posts
        posts = (
            db.query(models.UserPost)
            .options(joinedload(models.UserPost.user))
            .filter(models.UserPost.post_id.in_(post_ids))
            .all()
        )
        # Keep order according to saved order
        order_map = {pid: i for i, pid in enumerate(post_ids)}
        items: List[Dict[str, Any]] = []
        for post in posts:
            item = _collect_videos_for_post(post)
            if item.get("video_url"):
                items.append(item)
        items.sort(key=lambda it: order_map.get(int(it.get("id", 0)), 10**9))

        # Optionally attach reactions info (likes/dislikes and my_reaction)
        try:
            if items:
                pids = [int(it["id"]) for it in items if it.get("id")]
                _ensure_user_post_reactions_table(db)
                # my reaction
                my = db.execute(sql_text(
                    """
                    SELECT post_id, reaction FROM public.user_post_reactions
                    WHERE user_id = :uid AND post_id = ANY(:pids)
                    """
                ), {"uid": int(current_user.user_id), "pids": pids}).mappings().all()
                my_map = {int(r["post_id"]): int(r["reaction"]) for r in my or []}
                # counts
                counts = db.execute(sql_text(
                    """
                    SELECT post_id, reaction, COUNT(*)::INT AS count
                    FROM public.user_post_reactions
                    WHERE post_id = ANY(:pids)
                    GROUP BY post_id, reaction
                    """
                ), {"pids": pids}).mappings().all()
                likes_map: Dict[int, int] = {}
                dislikes_map: Dict[int, int] = {}
                for c in counts or []:
                    pid = int(c["post_id"])
                    react = int(c["reaction"])
                    cnt = int(c["count"])
                    if react == 1:
                        likes_map[pid] = cnt
                    elif react == -1:
                        dislikes_map[pid] = cnt
                for it in items:
                    pid = int(it["id"]) if it.get("id") else None
                    if pid is None:
                        continue
                    it["my_reaction"] = my_map.get(pid, 0)
                    it["likes"] = likes_map.get(pid, 0)
                    it["dislikes"] = dislikes_map.get(pid, 0)
        except Exception:
            pass

        return items
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to list saved posts: {str(e)}")

@router.get("/user/{user_id}", response_model=List[Dict[str, Any]])
async def list_user_public_videos(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(security.get_current_user_optional),
):
    """List videos for a given user.

    - If viewing own profile, return all posts with video paths.
    - Otherwise, return only public posts.
    Ordered by created_on DESC.
    """
    try:
        q = (
            db.query(models.UserPost)
            .options(joinedload(models.UserPost.user))
            .filter(models.UserPost.user_id == int(user_id))
            .filter(models.UserPost.post_path != None)
        )
        is_self = bool(current_user and int(getattr(current_user, "user_id", 0)) == int(user_id))
        if not is_self:
            q = q.filter(models.UserPost.public == True)
        posts = q.order_by(models.UserPost.created_on.desc()).limit(300).all()

        items: List[Dict[str, Any]] = []
        for post in posts:
            item = _collect_videos_for_post(post)
            if item.get("video_url"):
                items.append(item)

        # Attach reactions info for current_user
        try:
            if current_user is not None and items:
                pids = [int(it["id"]) for it in items if it.get("id")]
                _ensure_user_post_reactions_table(db)
                # my reaction
                my = db.execute(sql_text(
                    """
                    SELECT post_id, reaction FROM public.user_post_reactions
                    WHERE user_id = :uid AND post_id = ANY(:pids)
                    """
                ), {"uid": int(current_user.user_id), "pids": pids}).mappings().all()
                my_map = {int(r["post_id"]): int(r["reaction"]) for r in my or []}
                # counts
                counts = db.execute(sql_text(
                    """
                    SELECT post_id, reaction, COUNT(*)::INT AS count
                    FROM public.user_post_reactions
                    WHERE post_id = ANY(:pids)
                    GROUP BY post_id, reaction
                    """
                ), {"pids": pids}).mappings().all()
                likes_map: Dict[int, int] = {}
                dislikes_map: Dict[int, int] = {}
                for c in counts or []:
                    pid = int(c["post_id"])
                    react = int(c["reaction"]) 
                    cnt = int(c["count"]) 
                    if react == 1:
                        likes_map[pid] = cnt
                    elif react == -1:
                        dislikes_map[pid] = cnt
                for it in items:
                    pid = int(it["id"]) if it.get("id") else None
                    if pid is None:
                        continue
                    it["my_reaction"] = my_map.get(pid, 0)
                    it["likes"] = likes_map.get(pid, 0)
                    it["dislikes"] = dislikes_map.get(pid, 0)
        except Exception:
            pass

        return items
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to list user videos: {str(e)}")

# ===== Comments (Instagram-style) =====
class CommentCreate(BaseModel):
    text: str
    parent_comment_id: Optional[int] = None

def _ensure_comments_tables(db: Session) -> None:
    """Create comments and comment_likes tables if they do not exist.

    Schema:
      public.comments (
        comment_id BIGSERIAL PRIMARY KEY,
        post_id BIGINT NOT NULL REFERENCES public.user_posts(post_id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES public.users(user_id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
      public.comment_likes (
        comment_id BIGINT NOT NULL REFERENCES public.comments(comment_id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES public.users(user_id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (comment_id, user_id)
      )
    """
    try:
        db.execute(sql_text(
            """
            CREATE TABLE IF NOT EXISTS public.comments (
                comment_id BIGSERIAL PRIMARY KEY,
                post_id BIGINT NOT NULL REFERENCES public.user_posts(post_id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL REFERENCES public.users(user_id) ON DELETE CASCADE,
                parent_comment_id BIGINT NULL REFERENCES public.comments(comment_id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        ))
        db.execute(sql_text(
            """
            CREATE TABLE IF NOT EXISTS public.comment_likes (
                comment_id BIGINT NOT NULL REFERENCES public.comments(comment_id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL REFERENCES public.users(user_id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (comment_id, user_id)
            );
            """
        ))
        # Helpful indexes
        db.execute(sql_text(
            """
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='idx_comments_post_id_created'
                ) THEN
                    CREATE INDEX idx_comments_post_id_created ON public.comments (post_id, created_at DESC);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='idx_comments_parent_created'
                ) THEN
                    CREATE INDEX idx_comments_parent_created ON public.comments (post_id, parent_comment_id, created_at ASC);
                END IF;
            END $$;
            """
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise

@router.get("/{post_id}/comments")
async def list_comments(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(security.get_current_user_optional),
):
    """List comments for a post with like counts and whether current user liked each.

    Response: [
      { comment_id, user_id, user_name, profile_pic_url, text, created_at, likes: int, my_like: bool }
    ]
    """
    try:
        _ensure_comments_tables(db)
        rows = db.execute(sql_text(
            """
            SELECT c.comment_id, c.user_id, c.parent_comment_id, c.text, c.created_at,
                   u.user_name, u.profile_pic_url,
                   COALESCE(lc.likes_count, 0) AS likes
            FROM public.comments c
            JOIN public.users u ON u.user_id = c.user_id
            LEFT JOIN (
                SELECT comment_id, COUNT(*)::INT AS likes_count
                FROM public.comment_likes
                GROUP BY comment_id
            ) lc ON lc.comment_id = c.comment_id
            WHERE c.post_id = :pid
            ORDER BY c.created_at ASC
            """
        ), {"pid": int(post_id)}).mappings().all()

        my = {}
        if current_user is not None:
            liked = db.execute(sql_text(
                """
                SELECT comment_id
                FROM public.comment_likes
                WHERE user_id = :uid AND comment_id = ANY(
                    SELECT c.comment_id FROM public.comments c WHERE c.post_id = :pid
                )
                """
            ), {"uid": int(current_user.user_id), "pid": int(post_id)}).fetchall()
            for r in liked or []:
                try:
                    cid = int(r[0])
                    my[cid] = True
                except Exception:
                    pass

        out = []
        for r in rows or []:
            cid = int(r.get("comment_id"))
            out.append({
                "comment_id": cid,
                "user_id": int(r.get("user_id")),
                "parent_comment_id": (int(r.get("parent_comment_id")) if r.get("parent_comment_id") is not None else None),
                "user_name": r.get("user_name"),
                "profile_pic_url": r.get("profile_pic_url"),
                "text": r.get("text"),
                "created_at": r.get("created_at").isoformat() if r.get("created_at") else None,
                "likes": int(r.get("likes") or 0),
                "my_like": bool(my.get(cid, False)),
            })
        return out
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to list comments: {str(e)}")

@router.post("/{post_id}/comments")
async def create_comment(
    post_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(security.get_current_active_user),
):
    """Create a comment on a post."""
    try:
        _ensure_comments_tables(db)
        text = (payload.text or "").strip()
        if not text:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required")
        # Validate post exists
        post = db.query(models.UserPost).filter(models.UserPost.post_id == post_id).first()
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
        # Validate parent comment if provided (must belong to same post)
        parent_id = payload.parent_comment_id
        if parent_id is not None:
            owns = db.execute(sql_text(
                """
                SELECT 1 FROM public.comments WHERE comment_id = :cid AND post_id = :pid
                """
            ), {"cid": int(parent_id), "pid": int(post_id)}).fetchone()
            if not owns:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid parent_comment_id")

        # Insert comment
        row = db.execute(sql_text(
            """
            INSERT INTO public.comments (post_id, user_id, parent_comment_id, text, created_at)
            VALUES (:pid, :uid, :pcid, :txt, NOW())
            RETURNING comment_id, parent_comment_id, created_at
            """
        ), {"pid": int(post_id), "uid": int(current_user.user_id), "pcid": parent_id, "txt": text}).fetchone()
        db.commit()
        cid = int(row[0]) if row and len(row) > 0 else None
        parent_out = int(row[1]) if row and len(row) > 1 and row[1] is not None else None
        created_at = row[2].isoformat() if row and len(row) > 2 and row[2] else None
        return {
            "comment_id": cid,
            "user_id": int(current_user.user_id),
            "parent_comment_id": parent_out,
            "user_name": getattr(current_user, "user_name", None),
            "profile_pic_url": db.execute(sql_text("SELECT profile_pic_url FROM public.users WHERE user_id = :uid"), {"uid": int(current_user.user_id)}).fetchone()[0] if current_user else None,
            "text": text,
            "created_at": created_at,
            "likes": 0,
            "my_like": False,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create comment: {str(e)}")

@router.put("/comments/{comment_id}/like")
async def like_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(security.get_current_active_user),
):
    """Like a comment (idempotent)."""
    try:
        _ensure_comments_tables(db)
        db.execute(sql_text(
            """
            INSERT INTO public.comment_likes (comment_id, user_id, created_at)
            VALUES (:cid, :uid, NOW())
            ON CONFLICT (comment_id, user_id) DO NOTHING
            """
        ), {"cid": int(comment_id), "uid": int(current_user.user_id)})
        # Count likes
        row = db.execute(sql_text(
            """
            SELECT COUNT(*)::INT FROM public.comment_likes WHERE comment_id = :cid
            """
        ), {"cid": int(comment_id)}).fetchone()
        db.commit()
        return {"comment_id": int(comment_id), "likes": int(row[0]) if row else 0, "my_like": True}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to like comment: {str(e)}")

@router.delete("/comments/{comment_id}/like")
async def unlike_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(security.get_current_active_user),
):
    """Remove like from a comment (idempotent)."""
    try:
        _ensure_comments_tables(db)
        db.execute(sql_text(
            """
            DELETE FROM public.comment_likes WHERE comment_id = :cid AND user_id = :uid
            """
        ), {"cid": int(comment_id), "uid": int(current_user.user_id)})
        row = db.execute(sql_text(
            """
            SELECT COUNT(*)::INT FROM public.comment_likes WHERE comment_id = :cid
            """
        ), {"cid": int(comment_id)}).fetchone()
        db.commit()
        return {"comment_id": int(comment_id), "likes": int(row[0]) if row else 0, "my_like": False}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to unlike comment: {str(e)}")

@router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(security.get_current_active_user),
):
    """Delete own comment (cascades to child replies via FK)."""
    try:
        _ensure_comments_tables(db)
        row = db.execute(sql_text(
            """
            SELECT user_id FROM public.comments WHERE comment_id = :cid
            """
        ), {"cid": int(comment_id)}).fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
        if int(row[0]) != int(current_user.user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this comment")
        db.execute(sql_text("DELETE FROM public.comments WHERE comment_id = :cid"), {"cid": int(comment_id)})
        db.commit()
        return {"deleted": True, "comment_id": int(comment_id)}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete comment: {str(e)}")


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
    # print(f"Getting videos for user {user_id}")
    
    # First, get all posts for the user
    user_posts = db.query(models.UserPost).filter(
        models.UserPost.user_id == user_id,
        models.UserPost.post_path.isnot(None)  # Only include posts with a valid path
    ).order_by(models.UserPost.created_on.desc()).all()
    
    # Debug output
    # print(f"Found {len(user_posts)} total posts for user {user_id}")
    # for post in user_posts[:5]:  # Print first 5 posts for debugging
    #     print(f"Post ID: {post.post_id}, Type: {getattr(post, 'type', 'N/A')}, Path: {post.post_path}")
    # print(f"Found {len(user_posts)} posts for user {user_id}")
    
    videos = []
    
    for post in user_posts:
        if not post.post_path:
            # print(f"Skipping post {post.post_id} - no post_path")
            continue
            
        # print(f"\nProcessing post {post.post_id}")
        # print(f"Post path: {post.post_path}")
        # print(f"Post topic: {post.post_topic}")
        
        try:
            # print(f"\n--- Debugging Video Paths ---")
            # print(f"Original post_path: {post.post_path}")
            # print(f"Current working directory: {os.getcwd()}")

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

            # Handle UGC videos stored locally at C:/johnify/user-content/
            if pp.startswith("C:/johnify/user-content/"):
                # Extract filename
                filename = pp[len("C:/johnify/user-content/"):]
                video_dir_path = "C:/johnify/user-content"
                video_path = os.path.join(video_dir_path, filename)
                if os.path.exists(video_path):
                    # Build URLs
                    base_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip('/')
                    rel_path = f"user-content/{filename}"
                    video_url = f"{base_url}/videos/{rel_path}"

                    # Handle thumbnail (assume no thumbnail for now)
                    thumbnail_url = ""

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
                        "my_reaction": 0,
                        "likes": 0,
                        "dislikes": 0,
                    }
                else:
                    return {}

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
                
            # Split into directory and (optional) filename from post_path
            path_parts = normalized_path.split('/') if normalized_path else []
            last_part = path_parts[-1] if path_parts else ''
            if last_part.lower().endswith('.mp4'):
                # post_path points to a specific file; remember it and scan that directory
                directory_name = '/'.join(path_parts[:-1])
                video_filename = last_part
            else:
                # post_path points to a directory; we'll discover the mp4 below
                directory_name = '/'.join(path_parts)
                video_filename = None
            
            # Construct the full path to the video directory under the resolved generated root
            video_dir_path = os.path.join(str(GENERATED_ROOT), directory_name)
            video_dir_path = os.path.normpath(video_dir_path)  # Normalize the path for the current OS
            
            # print(f"Normalized video directory path: {video_dir_path}")
            # print(f"Directory exists: {os.path.exists(video_dir_path)}")
            
            # Resolve the actual video file we want to show
            video_path = None
            if os.path.exists(video_dir_path):
                # If a specific filename was provided in post_path, prefer that exact file
                if video_filename:
                    candidate = os.path.normpath(os.path.join(video_dir_path, video_filename))
                    if os.path.exists(candidate):
                        video_path = candidate
                    else:
                        # Fallback: pick the best matching .mp4 (prefer mlites_books*.mp4 if present)
                        pref = None
                        any_mp4 = None
                        for file in os.listdir(video_dir_path):
                            if file.lower().endswith('.mp4'):
                                if any_mp4 is None:
                                    any_mp4 = file
                                if file.startswith('mlites_books_'):
                                    pref = file
                                    break
                        pick = pref or any_mp4
                        if pick:
                            video_filename = pick
                            video_path = os.path.normpath(os.path.join(video_dir_path, pick))
                else:
                    # No filename specified: choose the best .mp4 in the directory
                    pref = None
                    any_mp4 = None
                    for file in os.listdir(video_dir_path):
                        if file.lower().endswith('.mp4'):
                            if any_mp4 is None:
                                any_mp4 = file
                            if file.startswith('mlites_books_'):
                                pref = file
                                break
                    pick = pref or any_mp4
                    if pick:
                        video_filename = pick
                        video_path = os.path.normpath(os.path.join(video_dir_path, pick))
            
            video_abs_path = os.path.abspath(video_path) if video_path else ""
            
            # print(f"Directory name: {directory_name}")
            # print(f"Found video file: {video_filename}" if video_filename else "No video file found")
            # print(f"Video directory path: {video_dir_path}")
            # print(f"Video path: {video_path}" if video_path else "No video path")
            # print(f"Absolute video path: {video_abs_path}" if video_abs_path else "No absolute path")
            # print(f"Directory exists: {os.path.exists(video_dir_path) if os.path.exists(video_dir_path) else False}")
            # print(f"File exists: {os.path.exists(video_path) if video_path else False}")
            
            # Check if the video file exists
            if video_path and os.path.exists(video_path):
                # print(f"✅ Video found at: {video_path}")
                
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
                
                # print(f"Generated video URL: {video_url}")
                # print(f"Generated thumbnail URL: {thumbnail_url}")
                # print(f"Video path: {video_path}")
                
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
                # print(f"❌ Video not found at: {video_path}")
                if video_dir_path and os.path.exists(video_dir_path):
                    # print(f"Directory contents: {os.listdir(video_dir_path)}")
                    pass
                else:
                    # print(f"Directory does not exist: {video_dir_path}")
                    pass
                    
        except Exception as e:
            import traceback
            # print(f"❌ Error processing video: {str(e)}")
            # print(f"Traceback: {traceback.format_exc()}")
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


@router.post("/upload")
async def upload_video(
    file: UploadFile = File(...),
    title: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(security.get_current_active_user),
):
    """Upload a user-generated video (UGC). Size limit 500MB. Stored in GCS prod or local generated/user-content/."""
    try:
        # Validate file
        if not file or not file.filename:
            raise HTTPException(status_code=400, detail="No file uploaded")
        fname = file.filename.lower()
        if not fname.endswith('.mp4'):
            raise HTTPException(status_code=400, detail="Only .mp4 videos allowed")
        
        # Check file size (500MB limit)
        content = await file.read()
        file_size_mb = len(content) / (1024 * 1024)
        if file_size_mb > 500:
            raise HTTPException(status_code=400, detail="Video size exceeds 500MB limit")
        
        uid = int(current_user.user_id)
        ts = int(datetime.utcnow().timestamp())
        title_clean = (title or "Untitled").strip()[:200]  # Limit title length
        
        if IS_PRODUCTION:
            # Upload to GCS
            from google.cloud import storage  # type: ignore
            bucket_name = "assets-johnify"
            object_path = f"content/content/users/{uid}_{ts}_{fname}"
            
            try:
                client = storage.Client()
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(object_path)
                blob.upload_from_string(content, content_type="video/mp4")
                try:
                    blob.make_public()
                except Exception:
                    pass
                post_path = f"gs://{bucket_name}/{object_path}"
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"GCS upload failed: {str(e)}")
        else:
            # Local storage
            user_content_dir = GENERATED_ROOT / "user-content"
            user_content_dir.mkdir(parents=True, exist_ok=True)
            local_filename = f"{uid}_{ts}_{fname}"
            local_path = user_content_dir / local_filename
            with open(local_path, "wb") as f:
                f.write(content)
            post_path = f"user-content/{local_filename}"
            
            # Generate thumbnail from first frame
            import subprocess
            thumb_filename = f"{local_filename.rsplit('.', 1)[0]}_thumb.jpg"
            thumb_path = user_content_dir / thumb_filename
            try:
                subprocess.run([
                    "ffmpeg", "-y", "-i", str(local_path), 
                    "-vf", "select=eq(n\\,0)", "-q:v", "3", "-frames:v", "1", 
                    str(thumb_path)
                ], check=True, capture_output=True)
                thumbnail_url = f"user-content/{thumb_filename}"
                print(f"Generated thumbnail: {thumb_path}")
            except subprocess.CalledProcessError as e:
                print(f"Failed to generate thumbnail: {e}")
                thumbnail_url = ""
        
        # Insert into user_posts
        new_post = models.UserPost(
            user_id=uid,
            post_topic=title_clean,
            post_path=post_path,
            public=True,  # Default to public
            type="ugc",
            created_on=datetime.utcnow(),
        )
        db.add(new_post)
        db.commit()
        db.refresh(new_post)
        
        return {
            "message": "Video uploaded successfully",
            "post_id": new_post.post_id,
            "title": title_clean,
            "size_mb": round(file_size_mb, 2),
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


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

        # Legacy likes table cleanup (disabled): user_posts_likes
        # try:
        #     db.execute(sql_text(
        #         """
        #         DELETE FROM public.user_posts_likes
        #         WHERE post_id = :post_id
        #         """
        #     ), {"post_id": post_id})
        # except Exception:
        #     # Do not fail the entire operation on likes cleanup issues; rollback handled below if needed
        #     pass

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

# --- Likes endpoints (legacy) disabled ---
# class LikeRequest(BaseModel):
#     action: Optional[str] = None  # e.g., 'like' (optional)

# @router.get("/{post_id}/likes")
# async def get_post_likes(
#     post_id: int,
#     db: Session = Depends(get_db),
# ):
#     """Return the like count for a post. Defaults to 0 when no row exists."""
#     try:
#         row = db.execute(sql_text(
#             """
#             SELECT likes_count
#             FROM public.user_posts_likes
#             WHERE post_id = :post_id
#             """
#         ), {"post_id": post_id}).fetchone()
#         count = int(row[0]) if row and row[0] is not None else 0
#         return {"likes_count": count}
#     except Exception as e:
#         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to fetch likes: {str(e)}")

# @router.post("/{post_id}/likes")
# async def like_post(
#     post_id: int,
#     payload: LikeRequest,
#     db: Session = Depends(get_db),
#     current_user: Optional[models.User] = Depends(security.get_current_active_user),
# ):
#     """Increment like count for a post (legacy)."""
#     try:
#         post = db.query(models.UserPost).filter(models.UserPost.post_id == post_id).first()
#         if not post:
#             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
#         if getattr(post, "user_id", None) == getattr(current_user, "user_id", None):
#             raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot like your own post")
#         updated = db.execute(sql_text(
#             """
#             UPDATE public.user_posts_likes
#             SET likes_count = COALESCE(likes_count, 0) + 1,
#                 updated_on = NOW()
#             WHERE post_id = :post_id
#             RETURNING likes_count
#             """
#         ), {"post_id": post_id}).fetchone()
#         new_count: Optional[int] = None
#         if updated and len(updated) > 0:
#             new_count = int(updated[0])
#         else:
#             inserted = db.execute(sql_text(
#                 """
#                 INSERT INTO public.user_posts_likes (post_id, likes_count, updated_on)
#                 VALUES (:post_id, 1, NOW())
#                 RETURNING likes_count
#                 """
#             ), {"post_id": post_id}).fetchone()
#             new_count = int(inserted[0]) if inserted and len(inserted) > 0 else 1
#         db.commit()
#         return {"likes_count": new_count}
#     except HTTPException:
#         db.rollback()
#         raise
#     except Exception as e:
#         db.rollback()
#         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to like post: {str(e)}")

# --- Reactions (per-user like/dislike) ---

class ReactionUpdate(BaseModel):
    reaction: int  # 1 for like, -1 for dislike

def _ensure_user_post_reactions_table(db: Session) -> None:
    """Create the reactions table if it doesn't exist.

    Schema:
      public.user_post_reactions (
        post_id BIGINT NOT NULL REFERENCES public.user_posts(post_id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES public.users(user_id) ON DELETE CASCADE,
        reaction SMALLINT NOT NULL CHECK (reaction IN (-1, 1)),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        PRIMARY KEY (post_id, user_id)
      )
    """
    try:
        db.execute(sql_text(
            """
            CREATE TABLE IF NOT EXISTS public.user_post_reactions (
                post_id BIGINT NOT NULL REFERENCES public.user_posts(post_id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL REFERENCES public.users(user_id) ON DELETE CASCADE,
                reaction SMALLINT NOT NULL CHECK (reaction IN (-1, 1)),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (post_id, user_id)
            );
            """
        ))
        # Helpful index for counts by post
        db.execute(sql_text(
            """
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='idx_upr_post_reaction'
                ) THEN
                    CREATE INDEX idx_upr_post_reaction ON public.user_post_reactions (post_id, reaction);
                END IF;
            END $$;
            """
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise

@router.get("/{post_id}/reactions")
async def get_post_reactions(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(security.get_current_user_optional),
):
    """Return like/dislike counts and the current user's reaction if authenticated.

    Response: { likes: int, dislikes: int, my_reaction: 1 | -1 | 0 }
    """
    try:
        _ensure_user_post_reactions_table(db)
        # Aggregate counts
        rows = db.execute(sql_text(
            """
            SELECT reaction, COUNT(*)::INT AS c
            FROM public.user_post_reactions
            WHERE post_id = :pid
            GROUP BY reaction
            """
        ), {"pid": int(post_id)}).mappings().all()
        likes = 0
        dislikes = 0
        for r in rows or []:
            try:
                if int(r.get("reaction")) == 1:
                    likes = int(r.get("c") or 0)
                elif int(r.get("reaction")) == -1:
                    dislikes = int(r.get("c") or 0)
            except Exception:
                pass

        my_reaction = 0
        if current_user is not None:
            me = db.execute(sql_text(
                """
                SELECT reaction
                FROM public.user_post_reactions
                WHERE post_id = :pid AND user_id = :uid
                LIMIT 1
                """
            ), {"pid": int(post_id), "uid": int(current_user.user_id)}).fetchone()
            if me and len(me) > 0:
                try:
                    my_reaction = int(me[0])
                except Exception:
                    my_reaction = 0

        return {"likes": likes, "dislikes": dislikes, "my_reaction": my_reaction}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to fetch reactions: {str(e)}")

@router.put("/{post_id}/reaction")
async def upsert_reaction(
    post_id: int,
    payload: ReactionUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(security.get_current_active_user),
):
    """Set current user's reaction (1 like, -1 dislike) for a post. Upsert semantics.
    Cannot react to your own post.
    """
    try:
        _ensure_user_post_reactions_table(db)
        # Validate post and ownership rule similar to likes endpoint
        post = db.query(models.UserPost).filter(models.UserPost.post_id == post_id).first()
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
        if getattr(post, "user_id", None) == getattr(current_user, "user_id", None):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot react to your own post")

        val = int(payload.reaction)
        if val not in (-1, 1):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="reaction must be 1 or -1")

        # Upsert reaction
        db.execute(sql_text(
            """
            INSERT INTO public.user_post_reactions (post_id, user_id, reaction, created_at, updated_at)
            VALUES (:pid, :uid, :val, NOW(), NOW())
            ON CONFLICT (post_id, user_id)
            DO UPDATE SET reaction = EXCLUDED.reaction, updated_at = NOW()
            """
        ), {"pid": int(post_id), "uid": int(current_user.user_id), "val": val})

        # Return updated counts and my_reaction
        rows = db.execute(sql_text(
            """
            SELECT reaction, COUNT(*)::INT AS c
            FROM public.user_post_reactions
            WHERE post_id = :pid
            GROUP BY reaction
            """
        ), {"pid": int(post_id)}).mappings().all()
        db.commit()

        likes = 0
        dislikes = 0
        for r in rows or []:
            try:
                if int(r.get("reaction")) == 1:
                    likes = int(r.get("c") or 0)
                elif int(r.get("reaction")) == -1:
                    dislikes = int(r.get("c") or 0)
            except Exception:
                pass
        return {"likes": likes, "dislikes": dislikes, "my_reaction": val}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to set reaction: {str(e)}")

@router.delete("/{post_id}/reaction")
async def delete_reaction(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(security.get_current_active_user),
):
    """Remove current user's reaction (make it neutral)."""
    try:
        _ensure_user_post_reactions_table(db)
        db.execute(sql_text(
            """
            DELETE FROM public.user_post_reactions
            WHERE post_id = :pid AND user_id = :uid
            """
        ), {"pid": int(post_id), "uid": int(current_user.user_id)})

        rows = db.execute(sql_text(
            """
            SELECT reaction, COUNT(*)::INT AS c
            FROM public.user_post_reactions
            WHERE post_id = :pid
            GROUP BY reaction
            """
        ), {"pid": int(post_id)}).mappings().all()
        db.commit()

        likes = 0
        dislikes = 0
        for r in rows or []:
            try:
                if int(r.get("reaction")) == 1:
                    likes = int(r.get("c") or 0)
                elif int(r.get("reaction")) == -1:
                    dislikes = int(r.get("c") or 0)
            except Exception:
                pass
        return {"likes": likes, "dislikes": dislikes, "my_reaction": 0}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete reaction: {str(e)}")
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
                    "my_reaction": 0,  # Default to no reaction
                    "likes": 0,  # Default to no likes
                    "dislikes": 0,  # Default to no dislikes
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
                "my_reaction": 0,  # Default to no reaction
                "likes": 0,  # Default to no likes
                "dislikes": 0,  # Default to no dislikes
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
        if directory_name == "user-content":
            # For UGC videos, thumbnail is named {video_filename_without_ext}_thumb.jpg
            video_name_without_ext = video_filename.rsplit('.', 1)[0]
            thumb_filename = f"{video_name_without_ext}_thumb.jpg"
            thumb_path = os.path.join(video_dir_path, thumb_filename)
            if os.path.exists(thumb_path):
                thumb_rel = os.path.relpath(thumb_path, GENERATED_ROOT).replace('\\', '/')
                thumbnail_url = f"{base_url}/videos/{thumb_rel}"
        else:
            # For AI-generated videos, look for thumbnail.jpg or any jpg/png
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
            "my_reaction": 0,  # Default to no reaction
            "likes": 0,  # Default to no likes
            "dislikes": 0,  # Default to no dislikes
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
                        "my_reaction": 0,  # Default to no reaction
                        "likes": 0,  # Default to no likes
                        "dislikes": 0,  # Default to no dislikes
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
                    "my_reaction": 0,  # Default to no reaction
                    "likes": 0,  # Default to no likes
                    "dislikes": 0,  # Default to no dislikes
                })
                continue

            item = _collect_videos_for_post(post)
            if item.get("video_url"):
                # Add default my_reaction to item
                item["my_reaction"] = 0
                out.append(item)
        
        # Fetch current user's reactions for all posts in the feed
        if current_user is not None and out:
            post_ids = [int(item["id"]) for item in out if item.get("id")]
            if post_ids:
                _ensure_user_post_reactions_table(db)
                reactions = db.execute(sql_text(
                    """
                    SELECT post_id, reaction
                    FROM public.user_post_reactions
                    WHERE user_id = :uid AND post_id = ANY(:pids)
                    """
                ), {"uid": int(current_user.user_id), "pids": post_ids}).mappings().all()
                
                # Create a lookup map for reactions
                reaction_map = {int(r["post_id"]): int(r["reaction"]) for r in reactions}
                
                # Update the my_reaction field for each item in the output
                for item in out:
                    post_id = int(item["id"])
                    item["my_reaction"] = reaction_map.get(post_id, 0)
        
        # Fetch reaction counts for all posts in the feed
        if out:
            post_ids = [int(item["id"]) for item in out if item.get("id")]
            if post_ids:
                _ensure_user_post_reactions_table(db)
                counts = db.execute(sql_text(
                    """
                    SELECT post_id, reaction, COUNT(*)::INT AS count
                    FROM public.user_post_reactions
                    WHERE post_id = ANY(:pids)
                    GROUP BY post_id, reaction
                    """
                ), {"pids": post_ids}).mappings().all()
                
                # Create lookup maps for likes and dislikes
                likes_map = {}
                dislikes_map = {}
                for c in counts:
                    post_id = int(c["post_id"])
                    reaction = int(c["reaction"])
                    count = int(c["count"])
                    if reaction == 1:
                        likes_map[post_id] = count
                    elif reaction == -1:
                        dislikes_map[post_id] = count
                
                # Update the likes and dislikes fields for each item in the output
                for item in out:
                    post_id = int(item["id"])
                    item["likes"] = likes_map.get(post_id, 0)
                    item["dislikes"] = dislikes_map.get(post_id, 0)
        
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
        
        # Fetch current user's reactions for all posts in both sections
        all_items = similar_items + other_items
        if current_user is not None and all_items:
            post_ids = [int(item["id"]) for item in all_items if item.get("id")]
            if post_ids:
                _ensure_user_post_reactions_table(db)
                reactions = db.execute(sql_text(
                    """
                    SELECT post_id, reaction
                    FROM public.user_post_reactions
                    WHERE user_id = :uid AND post_id = ANY(:pids)
                    """
                ), {"uid": int(current_user.user_id), "pids": post_ids}).mappings().all()
                
                # Create a lookup map for reactions
                reaction_map = {int(r["post_id"]): int(r["reaction"]) for r in reactions}
                
                # Update the my_reaction field for each item in both sections
                for section_items in [similar_items, other_items]:
                    for item in section_items:
                        post_id = int(item["id"])
                        item["my_reaction"] = reaction_map.get(post_id, 0)
        
        # Fetch reaction counts for all posts in both sections
        all_items = similar_items + other_items
        if all_items:
            post_ids = [int(item["id"]) for item in all_items if item.get("id")]
            if post_ids:
                _ensure_user_post_reactions_table(db)
                counts = db.execute(sql_text(
                    """
                    SELECT post_id, reaction, COUNT(*)::INT AS count
                    FROM public.user_post_reactions
                    WHERE post_id = ANY(:pids)
                    GROUP BY post_id, reaction
                    """
                ), {"pids": post_ids}).mappings().all()
                
                # Create lookup maps for likes and dislikes
                likes_map = {}
                dislikes_map = {}
                for c in counts:
                    post_id = int(c["post_id"])
                    reaction = int(c["reaction"])
                    count = int(c["count"])
                    if reaction == 1:
                        likes_map[post_id] = count
                    elif reaction == -1:
                        dislikes_map[post_id] = count
                
                # Update the likes and dislikes fields for each item in both sections
                for section_items in [similar_items, other_items]:
                    for item in section_items:
                        post_id = int(item["id"])
                        item["likes"] = likes_map.get(post_id, 0)
                        item["dislikes"] = dislikes_map.get(post_id, 0)
        
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
