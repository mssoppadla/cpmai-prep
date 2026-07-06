"""Public lead capture endpoint."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.orm import Session
from app.core.deps import get_db
from app.core.limiter import limiter
from app.core.settings_store import settings_store
from app.models.audit_log import AuditLog
from app.models.lead import Lead
from app.schemas.lead import LeadCreateIn, LeadCreateOut
from app.services.lead_scoring import calculate_lead_score
from app.services.tracking_service import emit_event
from app.services.geoip import extract_client_ip, lookup as geo_lookup

router = APIRouter()


def _emailed_within(db: Session, email: str, hours: int = 24) -> bool:
    """Anti-spam guard: has this email already received an automated
    offer reply in the last ``hours``? Reads the ``lead.offer_email_sent``
    audit events the mailer writes on success. We filter by action +
    recency in SQL, then match the email in Python (JSON-column lookups
    aren't portable across SQLite/Postgres, and the consented-signup
    volume per window is tiny)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (db.query(AuditLog)
            .filter(AuditLog.action == "lead.offer_email_sent",
                    AuditLog.created_at >= cutoff)
            .all())
    return any((r.metadata_json or {}).get("email") == email for r in rows)


def _maybe_send_offer_email(db: Session, lead: Lead,
                            background_tasks: BackgroundTasks) -> None:
    """Queue the lead → auto-offer reply when the gates pass:
    marketing consent given, automation switched on, and no offer email
    already sent to this address in the last 24h. Best-effort — the
    actual send happens off the request path in a BackgroundTask."""
    if not lead.consent_marketing:
        return
    if not settings_store.get_bool("email.automation_enabled", False):
        return
    if _emailed_within(db, lead.email):
        return
    from app.services.email import send_lead_offer_email
    background_tasks.add_task(send_lead_offer_email, lead.id)


@router.post("", response_model=LeadCreateOut, status_code=201)
@limiter.limit("3/minute")
def submit_lead(payload: LeadCreateIn, request: Request,
                background_tasks: BackgroundTasks,
                db: Session = Depends(get_db)):
    # Detect repeat-visitor BEFORE the insert — match on normalized
    # email OR on the anon_id cookie if present. Either signals "we've
    # seen this person before" → +15 in the scoring rules.
    email_lc = payload.email.lower()
    anon_id  = getattr(request.state, "anon_id", None)
    is_repeat = db.query(Lead.id).filter(
        (Lead.email == email_lc) |
        ((Lead.anon_id == anon_id) if anon_id else False)
    ).first() is not None

    # GeoIP enrichment — fail-open. Lookup returns None on any error
    # (no mmdb, private IP, MaxMind miss) and the lead row just has
    # NULL country/city. Never blocks the insert. The trusted-proxy
    # discipline in extract_client_ip protects against XFF spoofing.
    client_ip = extract_client_ip(request)
    geo = geo_lookup(client_ip) if client_ip else None

    lead = Lead(
        email=email_lc,
        name=payload.name, phone=payload.phone,
        country_code=payload.country_code,
        whatsapp_number=payload.whatsapp_number,
        linkedin_id=(payload.linkedin_id or None),
        company=payload.company, role=payload.role,
        source=payload.source,
        landing_url=payload.landing_url,
        referrer=request.headers.get("referer"),
        utm_source=payload.utm.source if payload.utm else None,
        utm_medium=payload.utm.medium if payload.utm else None,
        utm_campaign=payload.utm.campaign if payload.utm else None,
        utm_term=payload.utm.term if payload.utm else None,
        utm_content=payload.utm.content if payload.utm else None,
        interests=payload.interests,
        target_exam_date=payload.target_exam_date,
        experience_level=payload.experience_level,
        anon_id=anon_id,
        consent_marketing=payload.consent_marketing,
        consent_at=datetime.now(timezone.utc) if payload.consent_marketing else None,
        country=geo.country if geo else None,
        city=geo.city if geo else None,
    )
    # Compute the rule-based score from the assembled row + the
    # repeat-visitor flag. Pure-function; no extra DB hit.
    lead.score = calculate_lead_score(lead, is_repeat=is_repeat)
    db.add(lead); db.commit(); db.refresh(lead)
    emit_event(db, "lead.captured",
               anon_id=getattr(request.state, "anon_id", None),
               session_id=getattr(request.state, "session_id", None),
               request_id=getattr(request.state, "request_id", None),
               metadata={"source": payload.source.value, "lead_id": lead.id,
                         "country": lead.country})
    # Auto-reply with the 24h offer code when consent + automation are on.
    # Runs off the request path; never blocks or fails the sign-up.
    _maybe_send_offer_email(db, lead, background_tasks)
    # Lifecycle email automations (fail-soft): the lead.captured trigger
    # queues any admin-defined mail types for this landing-form
    # submission. Dedup is email-keyed, so a resubmitted form doesn't
    # re-fire once-per-user mail types. Coexists with the legacy
    # auto-offer above — admins avoid double-mailing by keeping ONE of
    # the two flows active (or via suppression groups within the engine).
    from app.services.email.automation import enqueue_for_lead_trigger
    enqueue_for_lead_trigger(
        db, "lead.captured", lead,
        context_extra={
            "lead_source": (lead.source.value
                            if hasattr(lead.source, "value")
                            else str(lead.source or "")),
            "target_exam_date": (lead.target_exam_date.strftime("%d %b %Y")
                                 if lead.target_exam_date else ""),
            "linkedin_id": lead.linkedin_id or "",
        })
    return LeadCreateOut(id=lead.id, message="Thanks — we'll be in touch shortly.")
