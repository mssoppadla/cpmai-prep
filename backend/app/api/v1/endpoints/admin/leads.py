"""Admin-only leads management."""
import csv, io
from datetime import date
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_admin_user
from app.core.exceptions import NotFoundError
from app.core.audit import audit_log
from app.models.lead import Lead
from app.models.user import User
from app.schemas.lead import LeadAdminOut

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
               limit: int = Query(50, le=200), offset: int = 0):
    query = _filter(db.query(Lead), source, q, from_date, to_date)
    return query.order_by(Lead.created_at.desc()).offset(offset).limit(limit).all()


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
    db.commit(); db.refresh(lead)
    audit_log(db, admin.id, "lead.notes_updated", {"lead_id": lead_id})
    return lead


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
            "consent_marketing", "converted_user_id", "created_at",
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
                lead.created_at.isoformat(),
            ])
            yield buf.getvalue(); buf.seek(0); buf.truncate()

    return StreamingResponse(
        gen(), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )
