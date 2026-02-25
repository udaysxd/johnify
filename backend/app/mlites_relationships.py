from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text as sql_text

from .database import get_db
from .auth import models, security
from .videos import _collect_videos_for_post  # reuse robust URL/thumbnail resolver

router = APIRouter(prefix="/api/mlites/relationships", tags=["mlites_relationships"]) 


def _ensure_user_post_reactions_table(db: Session) -> None:
    try:
        db.execute(sql_text(
            """
            CREATE TABLE IF NOT EXISTS public.user_post_reactions (
                user_id BIGINT NOT NULL REFERENCES public.users(user_id) ON DELETE CASCADE,
                post_id BIGINT NOT NULL REFERENCES public.user_posts(post_id) ON DELETE CASCADE,
                reaction SMALLINT NOT NULL,  -- 1 = like, -1 = dislike
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, post_id)
            );
            """
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        # Safe to ignore existence errors


@router.get("", response_model=List[Dict[str, Any]])
async def list_relationships_feed(
    limit: int = Query(30, ge=1, le=100),
    before_id: Optional[int] = Query(None, description="Return items with post_id < before_id for pagination"),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(security.get_current_user_optional),
):
    """Public feed of latest 'mlites_relationships' videos.
    Returns basic video items with resolved video_url and thumbnail_url.
    """
    try:
        q = (
            db.query(models.UserPost)
            .options(joinedload(models.UserPost.user))
            .filter(models.UserPost.post_path != None)
            .filter(models.UserPost.type == 'mlites_relationships')
            .filter(models.UserPost.public == True)
        )
        if before_id is not None:
            q = q.filter(models.UserPost.post_id < int(before_id))
        posts = q.order_by(models.UserPost.post_id.desc()).limit(int(limit)).all()
        items: List[Dict[str, Any]] = []
        for post in posts:
            item = _collect_videos_for_post(post)
            if item.get("video_url"):
                items.append(item)
        # Optional reactions metadata if user logged in
        try:
            if current_user is not None and items:
                pids = [int(it["id"]) for it in items if it.get("id")]
                _ensure_user_post_reactions_table(db)
                my = db.execute(sql_text(
                    """
                    SELECT post_id, reaction FROM public.user_post_reactions
                    WHERE user_id = :uid AND post_id = ANY(:pids)
                    """
                ), {"uid": int(current_user.user_id), "pids": pids}).mappings().all()
                my_map = {int(r["post_id"]): int(r["reaction"]) for r in my or []}
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
                    pid = int(c["post_id"]); react = int(c["reaction"]); cnt = int(c["count"]) 
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
        raise HTTPException(status_code=500, detail=f"Failed to list relationships videos: {str(e)}")


@router.get("/user/{user_id}", response_model=List[Dict[str, Any]])
async def list_user_relationships(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(security.get_current_user_optional),
):
    """List relationships videos for a user. If viewing self, include private; else only public."""
    try:
        q = (
            db.query(models.UserPost)
            .options(joinedload(models.UserPost.user))
            .filter(models.UserPost.user_id == int(user_id))
            .filter(models.UserPost.post_path != None)
            .filter(models.UserPost.type == 'mlites_relationships')
        )
        is_self = bool(current_user and int(getattr(current_user, "user_id", 0)) == int(user_id))
        if not is_self:
            q = q.filter(models.UserPost.public == True)
        posts = q.order_by(models.UserPost.created_on.desc()).limit(200).all()
        items: List[Dict[str, Any]] = []
        for post in posts:
            item = _collect_videos_for_post(post)
            if item.get("video_url"):
                items.append(item)
        return items
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list user relationships: {str(e)}")
