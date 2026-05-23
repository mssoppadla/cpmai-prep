"""APScheduler wrapper for social-automation campaigns.

Single AsyncIOScheduler started in the FastAPI lifespan (app/main.py).
On boot we load every active+published Campaign and register its cron
schedule. Campaign edits invalidate via ``reschedule()`` so live
changes don't require a restart.

# Why in-process rather than a separate worker

The volume is low (a few campaigns per tenant, each firing daily-ish).
Spinning up a Celery + Redis-queue + worker pod for this would be
overkill. In-process keeps:
  - Single deploy target (no worker container to operate)
  - Direct DB session access (no serialisation needed)
  - Easy local testing (just start the FastAPI dev server)

If volume grows past ~hundreds of campaigns or runs need genuine
parallelism, swap to a worker queue with the same WorkflowRunner API.

# Execution flow

  Scheduler tick fires
    │
    ├─→ Create CampaignRun(status="running")
    ├─→ Look up WORKFLOWS[campaign.workflow_type]
    ├─→ runner.run(campaign, db) → generated_content string
    └─→ Update run: status="done", finished_at, generated_content
        OR on exception: status="failed", error=traceback, finished_at

The runner's `.run()` is synchronous. APScheduler's AsyncIOScheduler
runs jobs in a thread executor so we don't block the event loop.
"""
from __future__ import annotations

import traceback
from datetime import datetime, timezone
from typing import Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.social import Campaign, CampaignRun
from app.services.social.runners import WORKFLOWS


log = structlog.get_logger("social.scheduler")


# Module-level singleton. Lifespan in app/main.py calls start()/stop().
_scheduler: Optional[AsyncIOScheduler] = None


def start() -> AsyncIOScheduler:
    """Start the scheduler + load all active campaigns. Idempotent."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.start()
    log.info("scheduler.started")
    _load_all_campaigns()
    return _scheduler


def stop() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")
    _scheduler = None


def reschedule(campaign_id: int) -> None:
    """Re-register a single campaign — call after admin edits a row.
    Removes any existing job + adds a fresh one if still active."""
    if _scheduler is None:
        return
    job_id = _job_id(campaign_id)
    try:
        _scheduler.remove_job(job_id)
    except Exception:
        pass  # not registered yet — fine
    with SessionLocal() as db:
        c = db.get(Campaign, campaign_id)
        if c and c.active and not c.is_deleted and c.schedule_cron:
            _register_campaign(c)


def _load_all_campaigns() -> None:
    with SessionLocal() as db:
        rows = db.query(Campaign).filter(
            Campaign.active.is_(True),
            Campaign.is_deleted.is_(False),
            Campaign.schedule_cron.isnot(None),
            Campaign.schedule_cron != "",
        ).all()
        for c in rows:
            try:
                _register_campaign(c)
            except Exception as e:
                log.warning("scheduler.register_failed",
                            campaign_id=c.id, error=str(e))


def _register_campaign(c: Campaign) -> None:
    if not c.schedule_cron:
        return
    try:
        trigger = CronTrigger.from_crontab(c.schedule_cron, timezone="UTC")
    except Exception as e:
        log.warning("scheduler.invalid_cron",
                    campaign_id=c.id, cron=c.schedule_cron, error=str(e))
        return
    if _scheduler is None:
        return
    _scheduler.add_job(
        execute_campaign,
        trigger=trigger,
        id=_job_id(c.id),
        args=(c.id,),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    log.info("scheduler.registered", campaign_id=c.id, cron=c.schedule_cron)


def _job_id(campaign_id: int) -> str:
    return f"campaign:{campaign_id}"


def execute_campaign(
    campaign_id: int,
    db: Optional[Session] = None,
) -> Optional[int]:
    """Fire a campaign. Creates a CampaignRun row, invokes the
    workflow runner, updates the run row to ``done`` or ``failed``.

    Returns the run id (useful for manual-trigger callers + tests).
    Returns None if the campaign vanished or was paused between
    scheduler-tick and execution.

    ``db``: when None (the APScheduler-driven path) we open a fresh
    SessionLocal. When provided (manual-trigger from an API endpoint,
    or a unit test) we reuse the caller's session so we share the
    same DB connection — required for the in-memory SQLite test DB
    where ``SessionLocal()`` would point at a different engine.
    """
    if db is not None:
        return _do_execute(db, campaign_id)
    with SessionLocal() as new_db:
        return _do_execute(new_db, campaign_id)


def _do_execute(db: Session, campaign_id: int) -> Optional[int]:
    c = db.get(Campaign, campaign_id)
    if c is None or c.is_deleted or not c.active:
        return None

    runner = WORKFLOWS.get(c.workflow_type)
    if runner is None:
        log.error("scheduler.unknown_workflow_type",
                  campaign_id=campaign_id, workflow_type=c.workflow_type)
        return None

    run = CampaignRun(
        tenant_id=c.tenant_id,
        campaign_id=c.id,
        status="running",
        posted_to_platforms=[],
    )
    db.add(run); db.commit(); db.refresh(run)

    try:
        content = runner.run(c, db)
        run.status = "done"
        run.generated_content = content
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        log.info("scheduler.run_done",
                 campaign_id=c.id, run_id=run.id,
                 content_chars=len(content or ""))
    except Exception as e:
        run.status = "failed"
        # Cap traceback at ~4KB so the DB row stays small.
        tb = traceback.format_exc()
        run.error = tb[:4096]
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        log.error("scheduler.run_failed",
                  campaign_id=c.id, run_id=run.id, error=str(e))

    return run.id
