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

# Ensure extended profile columns exist on first use
def _ensure_user_profile_columns(db: Session) -> None:
    """Ensure profile columns exist and enforce uniqueness (case-insensitive) only for non-null user_uid.

    - Keeps user_uid nullable (no mandatory requirement).
    - Repairs duplicates by nulling non-keeper rows.
    - Creates a partial unique index on lower(user_uid) WHERE user_uid IS NOT NULL.
    """
    try:
        # Ensure columns exist
        db.execute(text(
            """
            ALTER TABLE public.users
            ADD COLUMN IF NOT EXISTS bio TEXT,
            ADD COLUMN IF NOT EXISTS link TEXT,
            ADD COLUMN IF NOT EXISTS user_uid TEXT
            """
        ))
        db.commit()

        # Ensure column remains nullable (do not enforce NOT NULL)
        try:
            db.execute(text("ALTER TABLE public.users ALTER COLUMN user_uid DROP NOT NULL;"))
            db.commit()
        except Exception:
            db.rollback()

        # Drop any previous unique index name to avoid conflicts
        try:
            db.execute(text("DROP INDEX IF EXISTS ux_users_user_uid;"))
            db.commit()
        except Exception:
            db.rollback()

        # Repair duplicates (case-insensitive) among non-null, non-empty values by nulling non-keepers
        db.execute(text(
            """
            WITH dupe AS (
              SELECT lower(user_uid) AS lu, MIN(user_id) AS keeper
              FROM public.users
              WHERE user_uid IS NOT NULL AND user_uid <> ''
              GROUP BY lower(user_uid)
              HAVING COUNT(*) > 1
            )
            UPDATE public.users u
            SET user_uid = NULL
            FROM dupe d
            WHERE lower(u.user_uid) = d.lu AND u.user_id <> d.keeper
            """
        ))
        db.commit()

        # Create partial unique index enforcing uniqueness only when user_uid is not null
        db.execute(text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_users_user_uid_ci
            ON public.users (lower(user_uid))
            WHERE user_uid IS NOT NULL
            """
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        # Leave table accessible even if index creation fails
        return

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

    # Ensure columns exist and fetch extended profile fields
    _ensure_user_profile_columns(db)
    uid = int(getattr(current_user, "user_id", 0) or 0)
    row = db.execute(
        text(
            """
            SELECT profile_pic_url, bio, link, user_uid
            FROM public.users
            WHERE user_id = :uid
            LIMIT 1
            """
        ),
        {"uid": uid},
    ).fetchone() or [None, None, None, None]
    # Support Row or tuple-like
    if hasattr(row, "_mapping"):
        mapping = dict(row._mapping)  # type: ignore
        profile_pic_url = mapping.get("profile_pic_url")
        bio = mapping.get("bio")
        link = mapping.get("link")
        user_uid = mapping.get("user_uid")
    else:
        profile_pic_url, bio, link, user_uid = row[0], row[1], row[2], row[3]

    return {
        "user_id": uid,
        "user_email": getattr(current_user, "user_email", "") or "",
        "user_name": getattr(current_user, "user_name", None) or getattr(current_user, "user_email", ""),
        "is_verified": bool(getattr(current_user, "is_verified", True)),
        "created_on": getattr(current_user, "created_on", None),
        "updated_on": getattr(current_user, "updated_on", None),
        "uuid": getattr(current_user, "uuid", None),
        "active": _is_active(getattr(current_user, "active", True)),
        "profile_pic_url": profile_pic_url,
        # New fields for profile
        "bio": bio,
        "link": link,
        # Expose as userID in API while stored as user_uid in DB
        "userID": user_uid,
    }


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


@router.put("/me/profile")
async def update_my_profile(
    payload: dict,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Any:
    """Update current user's profile fields: bio, link, and userID (unique, required).

    Payload example:
    {
      "bio": "Lifelong learner",
      "link": "https://example.com/me",
      "userID": "john_doe"
    }
    """
    uid = int(getattr(current_user, "user_id", 0) or 0)
    if uid <= 0:
        raise HTTPException(status_code=401, detail="unauthorized")

    _ensure_user_profile_columns(db)

    bio = (payload or {}).get("bio")
    link = (payload or {}).get("link")
    user_uid = (payload or {}).get("userID")

    # Normalize/validate fields and enforce uniqueness (case-insensitive) for non-null values
    if user_uid is not None:
        if not isinstance(user_uid, str):
            raise HTTPException(status_code=400, detail="userID must be a string")
        user_uid = user_uid.strip()
        if user_uid == "":
            user_uid = None  # store as NULL
        else:
            # Uniqueness check (ignore current user's row)
            conflict = db.execute(
                text(
                    """
                    SELECT 1 FROM public.users
                    WHERE user_uid IS NOT NULL AND lower(user_uid) = lower(:u) AND user_id <> :me
                    LIMIT 1
                    """
                ),
                {"u": user_uid, "me": uid},
            ).fetchone()
            if conflict:
                raise HTTPException(status_code=409, detail="userID is already taken")

    try:
        # Build dynamic update
        sets = []
        params = {"me": uid}
        if bio is not None:
            sets.append("bio = :bio")
            params["bio"] = bio
        if link is not None:
            sets.append("link = :link")
            params["link"] = link
        if user_uid is not None:
            sets.append("user_uid = :user_uid")
            params["user_uid"] = user_uid

        if sets:
            sql = "UPDATE public.users SET " + ", ".join(sets) + ", updated_on = NOW() WHERE user_id = :me"
            db.execute(text(sql), params)
            db.commit()

        # Return updated snapshot
        row = db.execute(
            text(
                """
                SELECT user_id, user_name, user_email, profile_pic_url, bio, link, user_uid
                FROM public.users WHERE user_id = :me
                """
            ),
            {"me": uid},
        ).fetchone()
        if hasattr(row, "_mapping"):
            m = dict(row._mapping)  # type: ignore
            return {
                "user_id": m.get("user_id"),
                "user_email": m.get("user_email"),
                "user_name": m.get("user_name"),
                "profile_pic_url": m.get("profile_pic_url"),
                "bio": m.get("bio"),
                "link": m.get("link"),
                "userID": m.get("user_uid"),
            }
        else:
            return {
                "user_id": row[0],
                "user_email": row[2],
                "user_name": row[1],
                "profile_pic_url": row[3],
                "bio": row[4],
                "link": row[5],
                "userID": row[6],
            }
    except HTTPException:
        raise
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to update profile")


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

    Includes: user_id, user_name, profile_pic_url.
    """
    try:
        # Ensure columns exist and fetch extended fields for public profile
        _ensure_user_profile_columns(db)
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
            m = dict(row._mapping)  # type: ignore
            data = {
                "user_id": m.get("user_id"),
                "user_name": m.get("user_name"),
                "profile_pic_url": m.get("profile_pic_url"),
                "bio": m.get("bio"),
                "link": m.get("link"),
                "userID": m.get("user_uid"),
            }
        else:
            data = {
                "user_id": row[0],
                "user_name": row[1],
                "profile_pic_url": row[2],
                "bio": row[3],
                "link": row[4],
                "userID": row[5],
            }
        return data
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch user")
