"""Admin-only leads management — and unified Contacts feed."""
import csv, io
from datetime import date, datetime
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_admin_user
from app.core.exceptions import NotFoundError
from app.core.audit import audit_log
from app.api.v1.endpoints.admin.users import active_user_ids, user_activity_window, _user_lead_info
from app.models.lead import Lead
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.lead import ContactRow, LeadAdminOut

router = APIRouter()


def _filter(query, source: str | None, q: str | None,
            from_date: date | None, to_date: date | None):
    if source:
        query = query.filter(Lead.source == source)
    if q:
        query = query.filter(Lead.email.ilike(f"%{q}%"))
    if from_date:
        query = query.filter(Lead.created_at >= from_date)
    if to_date:
        query = query.filter(Lead.created_at <= to_date)
    return query


@router.get("", response_model=list[LeadAdminOut])
def list_leads(db: Session = Depends(get_db),
               source: str | None = None, q: str | None = None,
               from_date: date | None = Query(default=None, alias="from"),
               to_date: date | None = Query(default=None, alias="to"),
               # Admin can sort by recency (default) OR by score-desc
               # to triage warm leads first. Score-desc is the lead-
               # scoring feature's main UI hook.
               sort: str = Query("recent", pattern="^(recent|score)$"),
               limit: int = Query(50, le=200), offset: int = 0):
    query = _filter(db.query(Lead), source, q, from_date, to_date)
    if sort == "score":
        # NULL scores (pre-feature leads) sort last so warm leads
        # surface to the top. Tie-break on created_at-desc.
        query = query.order_by(Lead.score.desc().nulls_last(),
                                Lead.created_at.desc())
    else:
        query = query.order_by(Lead.created_at.desc())
    return query.offset(offset).limit(limit).all()


@router.get("/contacts", response_model=list[ContactRow])
def list_contacts(db: Session = Depends(get_db),
                  q: str | None = None,
                  kind: str | None = Query(None, pattern="^(lead|user)$"),
                  include_deleted: bool = Query(
                      False,
                      description="Include soft-deleted users in the feed. "
                                  "Default false — admins normally want "
                                  "the active-contacts view.",
                  ),
                  active_from: datetime | None = Query(
                      None, description="Only contacts active at/after this time: users who "
                                        "logged in OR performed an activity; leads submitted "
                                        "in the window (ISO 8601)."),
                  active_to: datetime | None = Query(
                      None, description="…at/before this time."),
                  limit: int = Query(200, le=500), offset: int = 0):
    """Unified feed of leads (landing-form submissions) + users
    (sign-ups via password or Google).

    Single ordered stream by created_at, so the admin can see "all the
    people who showed interest or signed up" in one place. Filter by
    kind=lead or kind=user when needed.

    Soft-deleted users are hidden by default; pass
    ``include_deleted=true`` to see tombstones (forensics / audit case).
    """
    rows: list[ContactRow] = []

    if kind != "user":
        lq = db.query(Lead)
        if q:
            lq = lq.filter(
                (Lead.email.ilike(f"%{q}%")) | (Lead.name.ilike(f"%{q}%"))
            )
        # A lead's "activity" is submitting the form — filter by when it came in.
        if active_from is not None:
            lq = lq.filter(Lead.created_at >= active_from)
        if active_to is not None:
            lq = lq.filter(Lead.created_at <= active_to)
        for L in lq.all():
            rows.append(ContactRow(
                kind="lead", id=L.id,
                email=L.email, name=L.name, created_at=L.created_at,
                source=L.source.value if hasattr(L.source, "value") else str(L.source),
                linkedin_id=L.linkedin_id,
                utm_campaign=L.utm_campaign,
                consent_marketing=L.consent_marketing,
                notes=L.notes,
                converted_user_id=L.converted_user_id,
                target_exam_date=L.target_exam_date,
                score=L.score,
                country=L.country,
                city=L.city,
            ))

    if kind != "lead":
        uq = db.query(User)
        if not include_deleted:
            uq = uq.filter(User.deleted_at.is_(None))
        if q:
            uq = uq.filter(
                (User.email.ilike(f"%{q}%")) | (User.name.ilike(f"%{q}%"))
            )
        if active_from is not None or active_to is not None:
            uq = uq.filter(user_activity_window(
                active_from, active_to, active_user_ids(db, active_from, active_to)))
        users = uq.all()
        if users:
            sub_ids = {s.user_id for s in db.query(Subscription)
                       .filter(Subscription.user_id.in_([u.id for u in users]),
                               Subscription.status == "active").all()}
            lead_info = _user_lead_info(db, users)   # alternate emails from linked leads
        else:
            sub_ids = set()
            lead_info = {}
        for U in users:
            rows.append(ContactRow(
                kind="user", id=U.id,
                email=U.email, name=U.name, created_at=U.created_at,
                role=U.role.value if hasattr(U.role, "value") else str(U.role),
                alt_emails=((lead_info.get(U.id) or {}).get("alt_emails") or None),
                # Admin-only notes now exist for users too (migration 0035),
                # so the Contacts feed surfaces + edits them for every row.
                notes=U.notes,
                has_google=bool(U.google_id),
                has_password=bool(U.password_hash),
                has_active_subscription=U.id in sub_ids,
                last_login_at=U.last_login_at,
                deleted_at=U.deleted_at,
                # GeoIP enrichment surfaced in the unified Contacts feed.
                # users.country/city are signup-time snapshots — "where
                # this person was when they created the account". For
                # rendering in /admin/leads, we PREFER the snapshot
                # (stable, more useful for cohort analysis) but fall
                # back to last_login_country if the snapshot is missing
                # — that handles users who pre-date the GeoIP feature
                # but have since logged in and got the last_login_*
                # fields populated.
                country=U.country or U.last_login_country,
                city=U.city,
            ))

    rows.sort(key=lambda r: r.created_at, reverse=True)
    return rows[offset:offset + limit]


# IMPORTANT: ``/export.csv`` MUST be declared BEFORE ``/{lead_id}``.
# FastAPI matches routes in declaration order; if ``/{lead_id}`` came
# first, a GET to ``/export.csv`` would try to coerce "export.csv" to
# an int and return 422 before this handler ever ran.
@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db),
               source: str | None = None, q: str | None = None,
               from_date: date | None = Query(default=None, alias="from"),
               to_date: date | None = Query(default=None, alias="to")):
    rows = (_filter(db.query(Lead), source, q, from_date, to_date)
            .order_by(Lead.created_at.desc()).all())

    def gen():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "id", "email", "name", "phone", "company", "role", "source",
            "utm_source", "utm_campaign", "target_exam_date",
            "consent_marketing", "converted_user_id", "score",
            "country", "city", "created_at",
        ])
        yield buf.getvalue(); buf.seek(0); buf.truncate()
        for lead in rows:
            writer.writerow([
                lead.id, lead.email, lead.name or "", lead.phone or "",
                lead.company or "", lead.role or "",
                lead.source.value if hasattr(lead.source, "value") else lead.source,
                lead.utm_source or "", lead.utm_campaign or "",
                lead.target_exam_date.isoformat() if lead.target_exam_date else "",
                lead.consent_marketing,
                lead.converted_user_id or "",
                lead.score if lead.score is not None else "",
                lead.country or "", lead.city or "",
                lead.created_at.isoformat(),
            ])
            yield buf.getvalue(); buf.seek(0); buf.truncate()

    return StreamingResponse(
        gen(), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


# ``/{lead_id}`` routes come AFTER ``/export.csv`` for the route-order
# reason explained above. Any additional non-parameterized GET routes
# should also go above this block.
@router.get("/{lead_id}", response_model=LeadAdminOut)
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead: raise NotFoundError()
    return lead


@router.patch("/{lead_id}/notes", response_model=LeadAdminOut)
def update_notes(lead_id: int, payload: dict,
                 db: Session = Depends(get_db),
                 admin: User = Depends(get_admin_user)):
    lead = db.get(Lead, lead_id)
    if not lead: raise NotFoundError()
    lead.notes = payload.get("notes", "")
    # Recompute the score: notes are an input to it, AND this also lets
    # admin opt-in-backfill the score for leads that pre-date the
    # scoring feature (just save the notes — even unchanged — to score).
    from app.services.lead_scoring import calculate_lead_score
    is_repeat = db.query(Lead.id).filter(
        Lead.id != lead.id,
        (Lead.email == lead.email) |
        ((Lead.anon_id == lead.anon_id) if lead.anon_id else False),
    ).first() is not None
    lead.score = calculate_lead_score(lead, is_repeat=is_repeat)
    db.commit(); db.refresh(lead)
    audit_log(db, admin.id, "lead.notes_updated",
              {"lead_id": lead_id, "score": lead.score})
    return lead


@router.delete("/{lead_id}", status_code=204)
def delete_lead(lead_id: int,
                db: Session = Depends(get_db),
                admin: User = Depends(get_admin_user)):
    """Hard-delete a lead. Used to drop junk landing-form submissions."""
    lead = db.get(Lead, lead_id)
    if not lead:
        raise NotFoundError()
    email = lead.email  # capture for audit
    db.delete(lead)
    db.commit()
    audit_log(db, admin.id, "lead.deleted",
              {"lead_id": lead_id, "email": email})
