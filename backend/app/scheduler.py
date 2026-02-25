import os
import logging
import asyncio
from datetime import datetime, time as dtime
from typing import Dict, List, Any

from sqlalchemy import text

from .database import Session
from . import lites as lites_module
from . import mlites as mlites_module

logger = logging.getLogger("scheduler")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] scheduler: %(message)s"))
    logger.addHandler(h)
logger.setLevel(logging.INFO)

# Optional: APScheduler for robust cron-like scheduling
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
except Exception:  # pragma: no cover
    AsyncIOScheduler = None  # type: ignore
    CronTrigger = None  # type: ignore

# Prefer stdlib zoneinfo; fall back gracefully to UTC
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

_scheduler = None

async def _collect_active_topics() -> Dict[int, List[Dict[str, Any]]]:
    """Return { user_id: [ {topic, minutes_per_day, topic_id}, ... ] } for active topics."""
    db = Session()
    try:
        rows = db.execute(text(
            """
            SELECT user_id, topic_id, topic, minutes_per_day
            FROM public.lites_topics
            WHERE active = TRUE
            ORDER BY user_id ASC, topic_id ASC
            """
        )).mappings().all()
        out: Dict[int, List[Dict[str, Any]]] = {}
        for r in rows:
            uid = int(r["user_id"])  # type: ignore[index]
            out.setdefault(uid, []).append({
                "topic_id": int(r["topic_id"]),
                "topic": r["topic"],
                "minutes_per_day": int(r["minutes_per_day"]) if r.get("minutes_per_day") is not None else 2,
            })
        return out
    finally:
        try:
            db.close()
        except Exception:
            pass

async def _run_daily_generation():
    """Job body: for each subscribed user, trigger Lites and MLites generation."""
    try:
        logger.info("daily generation job started")
        active = await _collect_active_topics()
        if not active:
            logger.info("no active topics found; skipping")
            return
        # Lites: run inline worker to ensure execution in scheduler context
        for uid, _topics in active.items():
            try:
                res = lites_module.run_lites_for_user(int(uid), max_per_topic=1)
                logger.info(f"lites inline result for user_id={uid}: {res}")
            except Exception as e:
                logger.exception(f"lites daily inline run failed for user_id={uid}: {e}")

        # MLites: run inline worker with the list of topics for each user
        for uid, topics in active.items():
            try:
                items = [{"topic": t["topic"], "minutes_per_day": t.get("minutes_per_day", 2)} for t in topics]
                if not items:
                    continue
                resm = mlites_module.run_mlites_for_user(int(uid), items)
                logger.info(f"mlites inline result for user_id={uid}: {resm}")
            except Exception as e:
                logger.exception(f"mlites daily inline run failed for user_id={uid}: {e}")

        logger.info("daily generation job completed dispatch")
    except Exception as e:
        logger.exception(f"daily generation job failed: {e}")

async def _run_once_at(target: dtime, tz):
    """Fallback scheduler if APScheduler is unavailable: sleep-until target daily loop."""
    from datetime import timedelta
    while True:
        now = datetime.now(tz=tz) if tz else datetime.now()
        run_dt = datetime.combine(now.date(), target)
        if tz:
            run_dt = run_dt.replace(tzinfo=tz)
        if run_dt <= now:
            run_dt = run_dt + timedelta(days=1)
        wait_s = (run_dt - now).total_seconds()
        logger.info(f"fallback scheduler sleeping {int(wait_s)}s until {run_dt.isoformat()} ({tz})")
        try:
            await asyncio.sleep(max(1.0, wait_s))
        except asyncio.CancelledError:
            raise
        await _run_daily_generation()

async def start_scheduler():
    """Initialize scheduler if enabled via env ENABLE_SCHEDULER=true.
    Env:
      - ENABLE_SCHEDULER: 'true' to enable
      - SCHEDULE_CRON: cron string like '0 6 * * *' (UTC) when APScheduler is available
      - SCHEDULE_TIME: 'HH:MM' 24h fallback when APScheduler unavailable
    """
    global _scheduler
    enable = os.getenv("ENABLE_SCHEDULER", "false").lower() == "true"
    if not enable:
        logger.info("scheduler disabled; set ENABLE_SCHEDULER=true to enable")
        return

    loop = asyncio.get_running_loop()

    tzname = os.getenv("TZ", "UTC")
    tz = None
    if ZoneInfo is not None:
        try:
            tz = ZoneInfo(tzname)
        except Exception:
            logger.warning(f"invalid TZ '{tzname}', defaulting to UTC")
            tz = ZoneInfo("UTC")

    if AsyncIOScheduler and CronTrigger:
        cron = os.getenv("SCHEDULE_CRON", "33 9 * * *")  # default 06:00 daily
        try:
            _scheduler = AsyncIOScheduler(timezone=tz)
            # CronTrigger can take a cron string via from_crontab; bind timezone explicitly
            trig = CronTrigger.from_crontab(cron, timezone=tz)
            _scheduler.add_job(_run_daily_generation, trigger=trig, id="daily_generation", replace_existing=True, max_instances=1)
            _scheduler.start()
            logger.info(f"APScheduler started with cron '{cron}', tz='{tzname}'")
        except Exception as e:
            logger.exception(f"failed to start APScheduler, falling back to sleep loop: {e}")
            # Fallback to simple loop
            hhmm = os.getenv("SCHEDULE_TIME", "06:00")
            try:
                hh, mm = [int(x) for x in hhmm.split(":", 1)]
            except Exception:
                hh, mm = 6, 0
            loop.create_task(_run_once_at(dtime(hour=hh, minute=mm), tz))
    else:
        # No APScheduler installed; simple fallback
        hhmm = os.getenv("SCHEDULE_TIME", "06:00")
        try:
            hh, mm = [int(x) for x in hhmm.split(":", 1)]
        except Exception:
            hh, mm = 6, 0
        loop.create_task(_run_once_at(dtime(hour=hh, minute=mm), tz))
        logger.info(f"fallback scheduler started for {hh:02d}:{mm:02d} daily, tz='{tzname}'")

async def shutdown_scheduler():
    global _scheduler
    try:
        if _scheduler:
            _scheduler.shutdown(wait=False)
            logger.info("APScheduler shutdown")
    except Exception:
        pass
