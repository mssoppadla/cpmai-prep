"""Nightly visitor_insights_daily rollup.

Aggregates yesterday's journey_events rows into the
visitor_insights_daily table so the /admin/insights/* dashboard can
read pre-aggregated counters instead of scanning live event rows.

Toggled by the ``tracking.rollup_enabled`` setting (default False).
Until ops flips it on, the dashboard reads live and this scheduler job
is registered but exits immediately on each tick.

We aggregate yesterday's complete day rather than the rolling 24h to
avoid races with the tracker still writing today's events. The
``ON CONFLICT … DO UPDATE`` pattern (or SQLite-portable equivalent)
means re-running the rollup for the same day is idempotent — useful
when the operator clicks a "Re-run rollup" admin button.

Grain decisions:
  * (tenant_id, day, NULL, NULL)              → all-pages all-events total
  * (tenant_id, day, NULL, event)             → per-event total for the day
  * (tenant_id, day, path, 'page.view')       → per-page page-view rollup
  * (tenant_id, day, path, NULL)              → per-page all-event total

We deliberately do NOT roll up at (path × event × hour) — the
dashboard's current granularity is per-day, and storing hourly would
multiply table size by 24× for no UI gain.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

import structlog
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.settings_store import settings_store
from app.models.journey_event import JourneyEvent
from app.models.visitor_insights_daily import VisitorInsightsDaily


log = structlog.get_logger("tracking.rollup")


def run_for_day(target: date | None = None) -> dict:
    """Materialise visitor_insights_daily for the given UTC date.

    If ``target`` is None, defaults to yesterday (so the job picks
    a "complete" day). Returns a small summary dict for the caller
    (admin-trigger endpoint or scheduler heartbeat log).
    """
    if not settings_store.get_bool("tracking.rollup_enabled", False):
        log.debug("rollup.skipped_disabled", target=str(target or "yday"))
        return {"skipped": True, "reason": "tracking.rollup_enabled=false"}

    if target is None:
        target = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    start = datetime.combine(target, time.min, tzinfo=timezone.utc)
    end   = start + timedelta(days=1)

    db: Session = SessionLocal()
    try:
        rows = (
            db.query(JourneyEvent)
            .filter(JourneyEvent.created_at >= start)
            .filter(JourneyEvent.created_at <  end)
            .all()
        )

        # Bucket keys: (tenant_id, path|None, event|None) → counters
        counters: dict[
            tuple[int, str | None, str | None],
            dict[str, object],
        ] = defaultdict(lambda: {
            "views": 0,
            "visitors": set(),
            "sessions": set(),
            "total_duration_ms": 0,
            "bounces": 0,
        })

        # First, group rows by (tenant_id, session_id) so we can compute
        # bounce (one-page session) without a second pass.
        sessions: dict[tuple[int, str], list[JourneyEvent]] = defaultdict(list)
        for r in rows:
            tid = r.tenant_id or 1
            if r.session_id:
                sessions[(tid, r.session_id)].append(r)

        # Sessions that bounced: exactly one page.view event
        bounced_sessions: set[tuple[int, str]] = set()
        for key, evs in sessions.items():
            page_views = [e for e in evs if e.event == "page.view"]
            if len(page_views) == 1:
                bounced_sessions.add(key)

        # Now per-row aggregation
        for r in rows:
            tid = r.tenant_id or 1
            v_key = (
                f"u:{r.user_id}" if r.user_id
                else (f"a:{r.anon_id}" if r.anon_id else None)
            )

            # The grain we write: 4 rows per event so the dashboard can
            # read at any axis.
            grains: list[tuple[int, str | None, str | None]] = [
                (tid, None, None),          # all-pages, all-events
                (tid, None, r.event),       # all-pages, this event
            ]
            if r.path:
                grains.append((tid, r.path, None))   # this page, all events
                grains.append((tid, r.path, r.event))  # this page, this event

            for grain in grains:
                c = counters[grain]
                if r.event == "page.view":
                    c["views"] = int(c["views"]) + 1  # type: ignore[arg-type]
                if v_key:
                    c["visitors"].add(v_key)          # type: ignore[union-attr]
                if r.session_id:
                    c["sessions"].add(r.session_id)    # type: ignore[union-attr]
                if r.duration_ms:
                    c["total_duration_ms"] = (
                        int(c["total_duration_ms"]) + r.duration_ms  # type: ignore[arg-type]
                    )

        # Bounces are per-(tenant_id, path|None) — the dashboard reads
        # them at all-events grain. We attribute to the path the
        # bouncing session's single page.view landed on.
        for (tid, sid), evs in sessions.items():
            if (tid, sid) not in bounced_sessions:
                continue
            pvs = [e for e in evs if e.event == "page.view"]
            if not pvs:
                continue
            landing = pvs[0].path
            # Bounces show up at:
            #   (tid, None, None) — tenant-day total
            #   (tid, None, 'page.view') — for KPI strip
            #   (tid, landing, None) — per-page bounce
            #   (tid, landing, 'page.view') — per-page bounce on page.view rollup
            for grain in [
                (tid, None, None),
                (tid, None, "page.view"),
                (tid, landing, None),
                (tid, landing, "page.view"),
            ]:
                counters[grain]["bounces"] = int(counters[grain]["bounces"]) + 1  # type: ignore[arg-type]

        # Upsert. SQLite (used by tests) doesn't support ON CONFLICT
        # the same way as Postgres so we delete-then-insert per (tenant,
        # day) bucket. The bucket size is small (~hundreds of rows) so
        # the perf hit is negligible.
        tenant_ids = {grain[0] for grain in counters.keys()}
        for tid in tenant_ids:
            db.query(VisitorInsightsDaily).filter(
                VisitorInsightsDaily.tenant_id == tid,
                VisitorInsightsDaily.day == target,
            ).delete(synchronize_session=False)

        for (tid, path, event), c in counters.items():
            db.add(VisitorInsightsDaily(
                tenant_id=tid,
                day=target,
                path=path,
                event=event,
                views=int(c["views"]),                       # type: ignore[arg-type]
                unique_visitors=len(c["visitors"]),          # type: ignore[arg-type]
                unique_sessions=len(c["sessions"]),          # type: ignore[arg-type]
                total_duration_ms=int(c["total_duration_ms"]),  # type: ignore[arg-type]
                bounces=int(c["bounces"]),                   # type: ignore[arg-type]
            ))
        db.commit()
        out = {
            "day":           target.isoformat(),
            "tenants":       len(tenant_ids),
            "rollup_rows":   len(counters),
            "source_events": len(rows),
        }
        log.info("rollup.completed", **out)
        return out

    except Exception as exc:  # noqa: BLE001 — rollup is best-effort
        db.rollback()
        log.error("rollup.failed", error=str(exc), target=str(target))
        return {"failed": True, "error": str(exc)}
    finally:
        db.close()


# ---------------------------------------------------------------------
# Scheduler integration
# ---------------------------------------------------------------------

# We piggyback on the same AsyncIOScheduler instance the social
# automation uses, registered in app/main.py startup. One job per
# process is enough — the rollup is idempotent and overlapping runs
# would just redo the same delete + insert.

def register(scheduler) -> None:
    """Register the nightly rollup job. Idempotent — replaces any
    existing job with the same id."""
    from apscheduler.triggers.cron import CronTrigger

    # 02:00 UTC daily. Late enough that yesterday's data is fully
    # written; early enough that operators querying at 09:00 see fresh
    # rollups.
    scheduler.add_job(
        run_for_day,
        CronTrigger(hour=2, minute=0, timezone="UTC"),
        id="visitor_insights.rollup",
        replace_existing=True,
        misfire_grace_time=3600,   # 1h leeway if the worker was down
    )
    log.info("rollup.job_registered")
