from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Any

from ..auth.security import get_current_active_user
from ..database import get_db
from . import schemas
from ..auth import models
import os, time, tempfile

router = APIRouter()


def _ensure_creators_program_table(db: Session) -> None:
    """Create the creators_program table if it does not exist."""
    try:
        db.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.creators_program (
                user_id INT PRIMARY KEY REFERENCES public.users(user_id) ON DELETE CASCADE,
                is_member BOOLEAN NOT NULL DEFAULT TRUE,
                joined_on TIMESTAMPTZ NULL
            );
            """
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise

@router.get("/me", response_model=schemas.UserResponse)
async def read_users_me(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> Any:
    """
    Get current user information
    """
    # Normalize 'active' to boolean to satisfy schema and avoid None/String types
    def _is_active(val) -> bool:
        if isinstance(val, bool):
            return val
        if val is None:
            # Default to True when missing to preserve access for legacy rows
            return True
        try:
            return str(val).strip().lower() in {"true", "1", "t", "yes", "y"}
        except Exception:
            return True

    # Fetch profile fields directly from DB
    row = db.execute(
        text(
            """
            SELECT profile_pic_url, bio, link, user_uid
            FROM public.users
            WHERE user_id = :uid
            LIMIT 1
            """
        ),
        {"uid": int(getattr(current_user, "user_id", 0) or 0)}
    ).fetchone()
    profile_pic_url, bio, link, user_uid = (row or [None, None, None, None])

    return {
        "user_id": int(getattr(current_user, "user_id", 0) or 0),
        "user_email": getattr(current_user, "user_email", "") or "",
        "user_name": getattr(current_user, "user_name", None) or getattr(current_user, "user_email", ""),
        "is_verified": bool(getattr(current_user, "is_verified", True)),
        "created_on": getattr(current_user, "created_on", None),
        "updated_on": getattr(current_user, "updated_on", None),
        "uuid": getattr(current_user, "uuid", None),
        "active": _is_active(getattr(current_user, "active", True)),
        "profile_pic_url": profile_pic_url,
        "bio": bio,
        "link": link,
        "user_uid": user_uid,
    }


@router.post("/me/creators-program/enroll")
async def enroll_creators_program(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> Any:
    uid = int(getattr(current_user, "user_id", 0) or 0)
    if uid <= 0:
        raise HTTPException(status_code=401, detail="unauthorized")

    _ensure_creators_program_table(db)

    try:
        row = db.execute(
            text(
                """
                INSERT INTO public.creators_program (user_id, is_member, joined_on)
                VALUES (:uid, TRUE, NOW())
                ON CONFLICT (user_id) DO UPDATE
                SET is_member = TRUE,
                    joined_on = COALESCE(public.creators_program.joined_on, EXCLUDED.joined_on)
                RETURNING user_id, is_member, joined_on
                """
            ),
            {"uid": uid},
        ).mappings().first()
        db.commit()

        joined_on = row.get("joined_on") if row else None
        return {
            "user_id": uid,
            "is_member": True,
            "joined_on": joined_on,
            "message": "Enrolled in creators program",
        }
    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to enroll: {str(e)}")


@router.get("/me/creators-program/status")
async def creators_program_status(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> Any:
    uid = int(getattr(current_user, "user_id", 0) or 0)
    if uid <= 0:
        raise HTTPException(status_code=401, detail="unauthorized")

    _ensure_creators_program_table(db)

    row = db.execute(
        text(
            """
            SELECT is_member, joined_on
            FROM public.creators_program
            WHERE user_id = :uid
            LIMIT 1
            """
        ),
        {"uid": uid},
    ).mappings().first()

    if not row:
        return {
            "user_id": uid,
            "is_member": False,
            "joined_on": None,
        }

    return {
        "user_id": uid,
        "is_member": bool(row.get("is_member", False)),
        "joined_on": row.get("joined_on"),
    }


@router.put("/me/profile")
@router.put("/me/profile/")
async def update_profile_fields(
    payload: schemas.UserProfileUpdate,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> Any:
    """Update current user's profile: bio, link, user_uid.

    - Creates columns if missing
    - Ensures unique index on user_uid
    - Validates link is a reasonable URL if provided
    """
    uid = int(getattr(current_user, "user_id", 0) or 0)
    if uid <= 0:
        raise HTTPException(status_code=401, detail="unauthorized")

    # Defensive: ensure columns and unique index exist
    try:
        db.execute(text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'bio'
                ) THEN
                    ALTER TABLE public.users ADD COLUMN bio TEXT NULL;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'link'
                ) THEN
                    ALTER TABLE public.users ADD COLUMN link VARCHAR(255) NULL;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'user_uid'
                ) THEN
                    ALTER TABLE public.users ADD COLUMN user_uid VARCHAR(100) NULL;
                END IF;
            END $$;
            """
        ))
        db.execute(text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_users_user_uid ON public.users(user_uid) WHERE user_uid IS NOT NULL;
            """
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        # Continue; columns may already exist

    # Normalize inputs
    new_bio = payload.bio if isinstance(payload.bio, str) else None
    if isinstance(new_bio, str):
        new_bio = new_bio.strip()
    new_link = payload.link if isinstance(payload.link, str) else None
    if isinstance(new_link, str):
        new_link = new_link.strip()
    new_uid = payload.user_uid if isinstance(payload.user_uid, str) else None
    if isinstance(new_uid, str):
        new_uid = new_uid.strip()

    # Basic link validation
    if new_link:
        low = new_link.lower()
        if not (low.startswith("http://") or low.startswith("https://")):
            raise HTTPException(status_code=400, detail="link must start with http:// or https://")

    # Enforce user_uid uniqueness (case-insensitive)
    if new_uid:
        exists = db.execute(
            text("SELECT 1 FROM public.users WHERE LOWER(user_uid) = LOWER(:u) AND user_id <> :me LIMIT 1"),
            {"u": new_uid, "me": uid},
        ).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail="user_uid is already taken")

    try:
        db.execute(
            text(
                """
                UPDATE public.users
                SET bio = COALESCE(:bio, bio),
                    link = COALESCE(:link, link),
                    user_uid = COALESCE(:user_uid, user_uid),
                    updated_on = NOW()
                WHERE user_id = :uid
                """
            ),
            {"bio": new_bio, "link": new_link, "user_uid": new_uid, "uid": uid},
        )
        db.commit()

        # Return the latest values
        row = db.execute(
            text(
                """
                SELECT profile_pic_url, bio, link, user_uid
                FROM public.users WHERE user_id = :uid
                """
            ),
            {"uid": uid},
        ).fetchone()
        profile_pic_url, bio, link, user_uid = (row or [None, None, None, None])
        return {
            "message": "Profile updated",
            "profile_pic_url": profile_pic_url,
            "bio": bio,
            "link": link,
            "user_uid": user_uid,
        }
    except HTTPException:
        raise
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to update profile")


@router.put("/me/profile-pic")
async def update_profile_pic(
    payload: dict,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> Any:
    """Update current user's profile picture URL.

    Expected payload: {"profile_pic_url": "https://..."}
    """
    try:
        url = (payload or {}).get("profile_pic_url")
        if not isinstance(url, str) or len(url.strip()) < 1:
            raise HTTPException(status_code=400, detail="profile_pic_url is required")
        url = url.strip()

        # Enforce storage base path
        BASE = "https://storage.googleapis.com/assets-johnify/userprofile/"
        if url.startswith("http://") or url.startswith("https://") or url.startswith("gs://"):
            if not url.startswith(BASE):
                raise HTTPException(status_code=400, detail=f"profile_pic_url must start with {BASE}")
        else:
            # Allow basename and expand to full URL
            # e.g., input: "u_123_avatar.jpg" => BASE + that
            url = BASE + url.lstrip("/")

        db.execute(
            text("""
                UPDATE public.users
                SET profile_pic_url = :url, updated_on = NOW()
                WHERE user_id = :uid
            """),
            {"url": url, "uid": int(getattr(current_user, "user_id", 0) or 0)}
        )
        db.commit()
        return {"message": "Profile picture updated", "profile_pic_url": url}
    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to update profile picture")


@router.post("/me/profile-pic/upload")
async def upload_profile_pic(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Upload profile image to GCS bucket path assets-johnify/userprofile/ and set profile_pic_url.

    Only enabled in production (ENVIRONMENT=production) where GCS credentials are available.
    """
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
    if ENVIRONMENT != "production":
        raise HTTPException(status_code=400, detail="Uploads are only enabled in production. Please paste a public URL instead.")

    bucket_name = "assets-johnify"  # explicitly target assets-johnify per requirement
    base_prefix = "userprofile/"

    # Validate file
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")
    fname = file.filename
    ext = os.path.splitext(fname)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(status_code=400, detail="Only .jpg, .jpeg, .png, .webp allowed")

    # Build destination path
    uid = int(getattr(current_user, "user_id", 0) or 0)
    ts = int(time.time())
    dest_name = f"u_{uid}_{ts}{ext}"
    object_path = base_prefix + dest_name

    # Save to temp and upload via GCS client
    try:
        from google.cloud import storage  # type: ignore
    except Exception:
        raise HTTPException(status_code=500, detail="google-cloud-storage not available")

    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=True) as tmp:
            content = await file.read()
            if not content:
                raise HTTPException(status_code=400, detail="Empty file")
            tmp.write(content)
            tmp.flush()

            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(object_path)

            content_type = file.content_type or {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
            }.get(ext, "application/octet-stream")

            blob.upload_from_filename(tmp.name, content_type=content_type)
            try:
                blob.make_public()
            except Exception:
                pass

        public_url = f"https://storage.googleapis.com/{bucket_name}/{object_path}"

        # Persist to users.profile_pic_url (and updated_on)
        db.execute(
            text(
                """
                UPDATE public.users
                SET profile_pic_url = :url, updated_on = NOW()
                WHERE user_id = :uid
                """
            ),
            {"url": public_url, "uid": uid},
        )
        db.commit()

        return {"message": "Uploaded", "profile_pic_url": public_url}
    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Upload failed")


# ---- Follow system ----
def _ensure_user_follows_table(db: Session) -> None:
    """Create the user_follows table if it does not exist."""
    try:
        db.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.user_follows (
                follower_id INT NOT NULL,
                followee_id INT NOT NULL,
                created_on TIMESTAMP DEFAULT NOW(),
                CONSTRAINT pk_user_follows PRIMARY KEY (follower_id, followee_id),
                CONSTRAINT fk_follower FOREIGN KEY (follower_id) REFERENCES public.users(user_id) ON DELETE CASCADE,
                CONSTRAINT fk_followee FOREIGN KEY (followee_id) REFERENCES public.users(user_id) ON DELETE CASCADE,
                CONSTRAINT chk_no_self_follow CHECK (follower_id <> followee_id)
            );
            CREATE INDEX IF NOT EXISTS idx_user_follows_followee ON public.user_follows(followee_id);
            CREATE INDEX IF NOT EXISTS idx_user_follows_follower ON public.user_follows(follower_id);
            """
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise


@router.post("/{user_id}/follow")
async def follow_user(
    user_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Any:
    """Follow a user (idempotent)."""
    uid = int(getattr(current_user, "user_id", 0) or 0)
    if uid <= 0:
        raise HTTPException(status_code=401, detail="unauthorized")
    if uid == int(user_id):
        raise HTTPException(status_code=400, detail="You cannot follow yourself")
    _ensure_user_follows_table(db)
    try:
        # Ensure target exists
        exists = db.execute(text("SELECT 1 FROM public.users WHERE user_id = :id LIMIT 1"), {"id": int(user_id)}).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="User not found")

        db.execute(
            text(
                """
                INSERT INTO public.user_follows (follower_id, followee_id)
                VALUES (:follower, :followee)
                ON CONFLICT (follower_id, followee_id) DO NOTHING
                """
            ),
            {"follower": uid, "followee": int(user_id)},
        )
        db.commit()

        # Return relationship & counts
        rel = db.execute(
            text(
                """
                SELECT
                  EXISTS(
                    SELECT 1 FROM public.user_follows
                    WHERE follower_id = :me AND followee_id = :them
                  ) AS is_following,
                  (SELECT COUNT(*) FROM public.user_follows WHERE followee_id = :them) AS followers_count,
                  (SELECT COUNT(*) FROM public.user_follows WHERE follower_id = :me) AS following_count
                """
            ),
            {"me": uid, "them": int(user_id)},
        ).mappings().first()
        return {
            "is_following": bool(rel.get("is_following", False)) if rel else True,
            "followers_count": int(rel.get("followers_count", 0)) if rel else 0,
            "following_count": int(rel.get("following_count", 0)) if rel else 0,
        }
    except HTTPException:
        raise
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to follow user")


@router.post("/{user_id}/unfollow")
async def unfollow_user(
    user_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Any:
    """Unfollow a user (idempotent)."""
    uid = int(getattr(current_user, "user_id", 0) or 0)
    if uid <= 0:
        raise HTTPException(status_code=401, detail="unauthorized")
    if uid == int(user_id):
        # Unfollowing self is a no-op
        return {"is_following": False}
    _ensure_user_follows_table(db)
    try:
        db.execute(
            text("DELETE FROM public.user_follows WHERE follower_id = :f AND followee_id = :t"),
            {"f": uid, "t": int(user_id)},
        )
        db.commit()

        rel = db.execute(
            text(
                """
                SELECT
                  FALSE AS is_following,
                  (SELECT COUNT(*) FROM public.user_follows WHERE followee_id = :them) AS followers_count,
                  (SELECT COUNT(*) FROM public.user_follows WHERE follower_id = :me) AS following_count
                """
            ),
            {"me": uid, "them": int(user_id)},
        ).mappings().first()
        return {
            "is_following": False,
            "followers_count": int(rel.get("followers_count", 0)) if rel else 0,
            "following_count": int(rel.get("following_count", 0)) if rel else 0,
        }
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to unfollow user")


@router.get("/{user_id}/relationship")
async def get_relationship(
    user_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Any:
    """Get relationship and counts between current user and target user."""
    uid = int(getattr(current_user, "user_id", 0) or 0)
    if uid <= 0:
        raise HTTPException(status_code=401, detail="unauthorized")
    _ensure_user_follows_table(db)
    try:
        rel = db.execute(
            text(
                """
                SELECT
                  EXISTS(
                    SELECT 1 FROM public.user_follows
                    WHERE follower_id = :me AND followee_id = :them
                  ) AS is_following,
                  (SELECT COUNT(*) FROM public.user_follows WHERE followee_id = :them) AS followers_count,
                  (SELECT COUNT(*) FROM public.user_follows WHERE follower_id = :them) AS following_count_target,
                  (SELECT COUNT(*) FROM public.user_follows WHERE follower_id = :me) AS following_count_me
                """
            ),
            {"me": uid, "them": int(user_id)},
        ).mappings().first()
        return {
            "is_following": bool(rel.get("is_following", False)) if rel else False,
            "followers_count": int(rel.get("followers_count", 0)) if rel else 0,
            "following_count": int(rel.get("following_count_target", 0)) if rel else 0,
            "me_following_count": int(rel.get("following_count_me", 0)) if rel else 0,
        }
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to get relationship")


@router.get("/{user_id}/followers/count")
async def followers_count(user_id: int, db: Session = Depends(get_db)) -> Any:
    _ensure_user_follows_table(db)
    row = db.execute(
        text("SELECT COUNT(*) FROM public.user_follows WHERE followee_id = :id"),
        {"id": int(user_id)},
    ).fetchone()
    return {"followers_count": int((row or [0])[0])}


@router.get("/{user_id}/following/count")
async def following_count(user_id: int, db: Session = Depends(get_db)) -> Any:
    _ensure_user_follows_table(db)
    row = db.execute(
        text("SELECT COUNT(*) FROM public.user_follows WHERE follower_id = :id"),
        {"id": int(user_id)},
    ).fetchone()
    return {"following_count": int((row or [0])[0])}


@router.get("/{user_id}")
async def get_public_user(
    user_id: int,
    db: Session = Depends(get_db)
) -> Any:
    """Public endpoint: return minimal user info for display purposes.

    Includes: user_id, user_name, profile_pic_url, bio, link, user_uid.
    """
    try:
        row = db.execute(
            text(
                """
                SELECT user_id, user_name, profile_pic_url, bio, link, user_uid
                FROM public.users
                WHERE user_id = :uid
                LIMIT 1
                """
            ),
            {"uid": int(user_id)},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        # row can be Row or tuple-like
        if hasattr(row, "_mapping"):
            data = dict(row._mapping)  # type: ignore
        else:
            data = {
                "user_id": row[0],
                "user_name": row[1],
                "profile_pic_url": row[2],
                "bio": row[3],
                "link": row[4],
                "user_uid": row[5],
            }
        return data
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch user")
