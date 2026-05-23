"""Admin endpoints for social-automation campaigns + social-queue.

/admin/campaigns           — CRUD on Campaign rows
/admin/campaigns/{id}/runs — list past runs (also the social queue
                             filter source)
/admin/campaigns/{id}/run-now — manual trigger (creates CampaignRun
                                synchronously, useful for testing
                                a workflow before letting cron drive it)
/admin/campaigns/workflows  — metadata for the admin form
/admin/social-queue         — flattened list of pending+failed runs
                              across all campaigns (with admin queue
                              actions: mark-posted, retry, delete)

All gated by ``get_admin_user`` at the parent router level.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.tenant import get_current_tenant_id
from app.models.social import Campaign, CampaignRun
from app.models.user import User
from app.schemas.social import (
    CampaignCreateIn, CampaignOut, CampaignRunOut, CampaignUpdateIn,
    MarkPostedIn, WorkflowMetaOut,
)
from app.services.social.runners import WORKFLOWS, workflow_meta
from app.services.social import scheduler as social_scheduler


router = APIRouter()


def _scope(db: Session):
    return db.query(Campaign).filter(
        Campaign.tenant_id == get_current_tenant_id(),
        Campaign.is_deleted.is_(False),
    )


# ──────────────────────────────────────────────────────────────────────
# Campaigns CRUD
# ──────────────────────────────────────────────────────────────────────
@router.get("/campaigns", response_model=list[CampaignOut])
def list_campaigns(
    db: Session = Depends(get_db),
    active: bool | None = Query(None),
    workflow_type: str | None = Query(None),
):
    q = _scope(db)
    if active is not None:
        q = q.filter(Campaign.active.is_(active))
    if workflow_type is not None:
        q = q.filter(Campaign.workflow_type == workflow_type)
    return q.order_by(Campaign.id.desc()).all()


@router.get("/campaigns/workflows", response_model=list[WorkflowMetaOut])
def list_workflows():
    """Drive the admin form's per-workflow field rendering."""
    return workflow_meta()


@router.get("/campaigns/{cid}", response_model=CampaignOut)
def get_campaign(cid: int, db: Session = Depends(get_db)):
    c = _scope(db).filter(Campaign.id == cid).first()
    if not c:
        raise NotFoundError("Campaign not found")
    return c


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
def create_campaign(
    payload: CampaignCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    if payload.workflow_type not in WORKFLOWS:
        raise ValidationError(
            f"Unknown workflow_type {payload.workflow_type!r}. "
            f"Valid: {sorted(WORKFLOWS.keys())}"
        )
    # Uniqueness check (composite uq_campaigns_tenant_name)
    existing = _scope(db).filter(Campaign.name == payload.name).first()
    if existing:
        raise ConflictError(f"Campaign with name {payload.name!r} already exists.")
    c = Campaign(
        tenant_id=get_current_tenant_id(),
        created_by=admin.id,
        **payload.model_dump(),
    )
    db.add(c); db.commit(); db.refresh(c)
    audit_log(db, admin.id, "campaign.created",
              {"id": c.id, "name": c.name, "workflow_type": c.workflow_type})
    # Register with the scheduler (idempotent — handles no-cron case)
    try:
        social_scheduler.reschedule(c.id)
    except Exception:
        pass  # scheduler may be paused in test env
    return c


@router.patch("/campaigns/{cid}", response_model=CampaignOut)
def update_campaign(
    cid: int,
    payload: CampaignUpdateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    c = _scope(db).filter(Campaign.id == cid).first()
    if not c:
        raise NotFoundError("Campaign not found")
    updates = payload.model_dump(exclude_unset=True)
    if "workflow_type" in updates and updates["workflow_type"] not in WORKFLOWS:
        raise ValidationError(f"Unknown workflow_type {updates['workflow_type']!r}.")
    if "name" in updates and updates["name"] != c.name:
        clash = _scope(db).filter(Campaign.name == updates["name"],
                                  Campaign.id != cid).first()
        if clash:
            raise ConflictError(f"Campaign with name {updates['name']!r} already exists.")
    for k, v in updates.items():
        setattr(c, k, v)
    db.commit(); db.refresh(c)
    audit_log(db, admin.id, "campaign.updated",
              {"id": c.id, "changed": sorted(updates.keys())})
    try:
        social_scheduler.reschedule(c.id)
    except Exception:
        pass
    return c


@router.delete("/campaigns/{cid}", status_code=204)
def delete_campaign(
    cid: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    c = _scope(db).filter(Campaign.id == cid).first()
    if not c:
        raise NotFoundError("Campaign not found")
    c.is_deleted = True
    c.deleted_at = datetime.now(timezone.utc)
    c.deleted_by = admin.id
    c.active = False
    db.commit()
    audit_log(db, admin.id, "campaign.deleted", {"id": c.id, "name": c.name})
    try:
        social_scheduler.reschedule(c.id)  # removes job since active=False
    except Exception:
        pass


@router.post("/campaigns/{cid}/run-now", response_model=CampaignRunOut)
def run_campaign_now(
    cid: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Manual trigger — invokes execute_campaign synchronously.

    Lets the operator see the generated output IMMEDIATELY without
    waiting for the next cron tick. Useful when first authoring a
    campaign + verifying the prompt produces good content.
    """
    c = _scope(db).filter(Campaign.id == cid).first()
    if not c:
        raise NotFoundError("Campaign not found")
    if c.workflow_type not in WORKFLOWS:
        raise ValidationError(f"Unknown workflow_type {c.workflow_type!r}.")
    # Reuse the request's session so the SAME DB the campaign lives
    # in is the one we write the run to. Critical for the test path
    # where SessionLocal() points at a different (real Postgres)
    # engine than the test's in-memory SQLite.
    run_id = social_scheduler.execute_campaign(c.id, db=db)
    if run_id is None:
        raise ValidationError(
            "Campaign could not be executed (paused or workflow unregistered)."
        )
    run = db.get(CampaignRun, run_id)
    audit_log(db, admin.id, "campaign.manual_run",
              {"campaign_id": c.id, "run_id": run.id, "status": run.status})
    return run


# ──────────────────────────────────────────────────────────────────────
# Per-campaign runs list
# ──────────────────────────────────────────────────────────────────────
@router.get("/campaigns/{cid}/runs", response_model=list[CampaignRunOut])
def list_runs(
    cid: int,
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    c = _scope(db).filter(Campaign.id == cid).first()
    if not c:
        raise NotFoundError("Campaign not found")
    return (db.query(CampaignRun)
              .filter(CampaignRun.campaign_id == c.id,
                      CampaignRun.tenant_id == get_current_tenant_id())
              .order_by(CampaignRun.started_at.desc())
              .limit(limit).all())


# ──────────────────────────────────────────────────────────────────────
# Social queue — flattened cross-campaign view for admin posting
# ──────────────────────────────────────────────────────────────────────
@router.get("/social-queue", response_model=list[CampaignRunOut])
def list_social_queue(
    db: Session = Depends(get_db),
    status: str | None = Query(
        None, description="Filter by run status (queued|running|done|posted|failed)"),
    limit: int = Query(100, ge=1, le=500),
):
    """The /admin/social-queue UI's primary feed. Defaults to all
    runs not yet posted (status in done|failed)."""
    q = db.query(CampaignRun).filter(
        CampaignRun.tenant_id == get_current_tenant_id(),
    )
    if status:
        q = q.filter(CampaignRun.status == status)
    else:
        # Default: show what needs admin attention — done (ready to
        # post) + failed (needs review). Hide running + queued + posted.
        q = q.filter(CampaignRun.status.in_(["done", "failed"]))
    return q.order_by(CampaignRun.started_at.desc()).limit(limit).all()


@router.post("/social-queue/{run_id}/mark-posted",
             response_model=CampaignRunOut)
def mark_run_posted(
    run_id: int,
    payload: MarkPostedIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Admin clicked 'Mark posted' in the queue UI after manually
    posting to a platform. Records the platform + URL so the queue
    can deep-link back later."""
    run = db.query(CampaignRun).filter(
        CampaignRun.id == run_id,
        CampaignRun.tenant_id == get_current_tenant_id(),
    ).first()
    if not run:
        raise NotFoundError("Run not found")
    posted = list(run.posted_to_platforms or [])
    posted.append({
        "platform": payload.platform,
        "url": payload.url,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    run.posted_to_platforms = posted
    run.status = "posted"
    run.posted_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(run)
    audit_log(db, admin.id, "campaign_run.marked_posted",
              {"run_id": run.id, "platform": payload.platform})
    return run


@router.post("/social-queue/{run_id}/retry", response_model=CampaignRunOut)
def retry_run(
    run_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Re-execute the run's parent campaign synchronously. Creates a
    NEW CampaignRun row (the original failed run is preserved as a
    historical record)."""
    run = db.query(CampaignRun).filter(
        CampaignRun.id == run_id,
        CampaignRun.tenant_id == get_current_tenant_id(),
    ).first()
    if not run:
        raise NotFoundError("Run not found")
    new_run_id = social_scheduler.execute_campaign(run.campaign_id, db=db)
    if new_run_id is None:
        raise ValidationError("Could not retry — campaign paused or removed.")
    new_run = db.get(CampaignRun, new_run_id)
    audit_log(db, admin.id, "campaign_run.retried",
              {"original_run_id": run.id, "new_run_id": new_run_id,
               "status": new_run.status})
    return new_run
