from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Any, Dict, List, Optional

from .database import get_db
from .auth.security import get_current_user
from .auth import models

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


def _ensure_user_preferences_table(db: Session) -> None:
    """Create user preferences table if it does not exist.

    Structure:
      public.user_preferences (
        user_id INT PRIMARY KEY REFERENCES public.users(user_id),
        language_id INT NULL,
        topic_ids INT[] NULL,
        updated_on TIMESTAMP DEFAULT NOW()
      )
    """
    try:
        db.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.user_preferences (
                user_id INT PRIMARY KEY REFERENCES public.users(user_id),
                language_id INT NULL,
                topic_ids INT[] NULL,
                updated_on TIMESTAMP DEFAULT NOW()
            );
            -- Add columns if the table exists but columns are missing
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='user_preferences' AND column_name='topic_ids'
                ) THEN
                    ALTER TABLE public.user_preferences ADD COLUMN topic_ids INT[] NULL;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='user_preferences' AND column_name='language_id'
                ) THEN
                    ALTER TABLE public.user_preferences ADD COLUMN language_id INT NULL;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='user_preferences' AND column_name='updated_on'
                ) THEN
                    ALTER TABLE public.user_preferences ADD COLUMN updated_on TIMESTAMP DEFAULT NOW();
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


def _ensure_user_topics_table(db: Session) -> None:
    """Create user_topics table to track which topics a user has opted into.

    Structure:
      public.user_topics (
        id SERIAL PRIMARY KEY,
        user_id INT NOT NULL REFERENCES public.users(user_id) ON DELETE CASCADE,
        topic_id INT NOT NULL,
        created_on TIMESTAMP DEFAULT NOW(),
        UNIQUE(user_id, topic_id)
      )
    """
    try:
        db.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.user_topics (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL REFERENCES public.users(user_id) ON DELETE CASCADE,
                topic_id INT NOT NULL,
                created_on TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id, topic_id)
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


def _insert_user_topics(db: Session, user_id: int, topic_ids: list[int]) -> None:
    if not topic_ids:
        return
    try:
        _ensure_user_topics_table(db)
        # Insert new mappings, ignore existing via ON CONFLICT
        for tid in topic_ids:
            try:
                db.execute(text(
                    """
                    INSERT INTO public.user_topics (user_id, topic_id)
                    VALUES (:uid, :tid)
                    ON CONFLICT (user_id, topic_id) DO NOTHING
                    """
                ), {"uid": int(user_id), "tid": int(tid)})
            except Exception:
                pass
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        # Non-fatal


def _get_topic_names(db: Session, topic_ids: list[int]) -> list[str]:
    if not topic_ids:
        return []
    try:
        rows = db.execute(text(
            """
            SELECT id, topics_name
            FROM topics_master
            WHERE id = ANY(:ids)
            """
        ), {"ids": topic_ids}).mappings().all()
        return [str(r.get("topics_name")) for r in rows if r.get("topics_name")]
    except Exception:
        return []


def _fire_create_mlites_for_topics(user_id: int, topic_names: list[str]) -> None:
    """Background task to request one MLites video per topic via the local HTTP endpoint."""
    if not topic_names:
        return
    import os, json
    import requests  # type: ignore

    backend_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip('/')
    url = f"{backend_url}/api/mlites"
    payload = {
        "topics": [{"topic": name, "minutes_per_day": 2} for name in topic_names],
        "user_id": int(user_id),
    }
    try:
        # Best-effort call; do not raise
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        requests.post(url, data=json.dumps(payload), headers=headers, timeout=10)
    except Exception:
        # Swallow errors to avoid impacting the preferences response
        pass


@router.get("/languages")
def get_languages(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Return all languages from language_master as list of {id, lang, lang_code}.

    Supports either column name variant: "lang-code" or lang_code.
    """
    try:
        # Try common snake_case column first
        try:
            rows = db.execute(text(
                """
                SELECT id,
                       lang,
                       lang_code AS lang_code
                FROM language_master
                ORDER BY lang ASC
                """
            )).mappings().all()
            return [dict(r) for r in rows]
        except Exception as e_snake:
            # Fallback to hyphenated column name
            try:
                rows = db.execute(text(
                    """
                    SELECT id,
                           lang,
                           "lang-code" AS lang_code
                    FROM language_master
                    ORDER BY lang ASC
                    """
                )).mappings().all()
                return [dict(r) for r in rows]
            except Exception as e_hyphen:
                raise HTTPException(status_code=500, detail=f"Failed to fetch languages: tried lang_code ({e_snake}) and \"lang-code\" ({e_hyphen})")
    except HTTPException:
        raise


@router.get("/topics")
def get_topics(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Return active topics from topics_master as list of {id, topics_name}."""
    try:
        rows = db.execute(text(
            """
            SELECT id, topics_name
            FROM topics_master
            WHERE active = TRUE
            ORDER BY topics_name ASC
            """
        )).mappings().all()
        return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch topics: {e}")


@router.post("")
def save_preferences(background_tasks: BackgroundTasks, payload: Dict[str, Any], db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)) -> Dict[str, Any]:
    """Save the user's selected language and topic IDs.

    Expected payload: {"language_id": int | None, "topic_ids": List[int]}
    Business rules: topic_ids length 0..5, language one or none.
    """
    language_id: Optional[int] = payload.get("language_id")
    topic_ids: List[int] = payload.get("topic_ids") or []

    # Validate topic_ids
    if not isinstance(topic_ids, list) or any(not isinstance(t, int) for t in topic_ids):
        raise HTTPException(status_code=400, detail="topic_ids must be a list of integers")
    if len(topic_ids) > 5:
        raise HTTPException(status_code=400, detail="You can select up to 5 interests")

    # Validate language_id
    if language_id is not None and not isinstance(language_id, int):
        raise HTTPException(status_code=400, detail="language_id must be an integer or null")

    try:
        _ensure_user_preferences_table(db)

        # If no language specified, default to English if available
        if language_id is None:
            try:
                row = db.execute(text(
                    """
                    SELECT id
                    FROM language_master
                    WHERE LOWER(lang) = 'english'
                    LIMIT 1
                    """
                )).mappings().first()
                if row and (row.get("id") is not None if isinstance(row, dict) else getattr(row, "id", None) is not None):
                    language_id = int(row["id"] if isinstance(row, dict) else row.id)
            except Exception:
                # If lookup fails, proceed without defaulting
                pass

        # Capture existing topics to detect new selections
        prev_topics_row = db.execute(text(
            """
            SELECT topic_ids FROM public.user_preferences WHERE user_id = :uid LIMIT 1
            """
        ), {"uid": int(current_user.user_id)}).mappings().first()
        prev_topic_ids = []
        try:
            if prev_topics_row is not None:
                prev = prev_topics_row.get("topic_ids")
                if isinstance(prev, list):
                    prev_topic_ids = [int(x) for x in prev]
        except Exception:
            prev_topic_ids = []

        # Upsert into user_preferences
        db.execute(text(
            """
            INSERT INTO public.user_preferences (user_id, language_id, topic_ids, updated_on)
            VALUES (:uid, :lang_id, :topics, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET language_id = EXCLUDED.language_id,
                          topic_ids = EXCLUDED.topic_ids,
                          updated_on = NOW();
            """
        ), {
            "uid": int(current_user.user_id),
            "lang_id": language_id,
            "topics": topic_ids if len(topic_ids) > 0 else None,
        })
        db.commit()

        # Determine newly added topics and record them in user_topics
        new_topic_ids = [tid for tid in topic_ids if tid not in prev_topic_ids]
        if new_topic_ids:
            _insert_user_topics(db, int(current_user.user_id), new_topic_ids)
            # Fire one MLite per new topic via background task
            topic_names = _get_topic_names(db, new_topic_ids)
            if topic_names:
                background_tasks.add_task(_fire_create_mlites_for_topics, int(current_user.user_id), topic_names)

        return {"message": "Preferences saved"}
    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to save preferences")


@router.get("")
def get_user_preferences(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)) -> Dict[str, Any]:
    """Return current user's saved preferences.

    Shape: { language_id: int | None, topic_ids: List[int] }
    """
    try:
        _ensure_user_preferences_table(db)
        row = db.execute(text(
            """
            SELECT language_id, topic_ids
            FROM public.user_preferences
            WHERE user_id = :uid
            LIMIT 1
            """
        ), {"uid": int(current_user.user_id)}).mappings().first()
        if not row:
            return {"language_id": None, "topic_ids": []}
        lang_id = row.get("language_id") if isinstance(row, dict) else row.language_id
        topics = row.get("topic_ids") if isinstance(row, dict) else row.topic_ids
        # Normalize None -> [] for topic_ids
        if topics is None:
            topics = []
        return {"language_id": lang_id, "topic_ids": list(topics)}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch user preferences")
