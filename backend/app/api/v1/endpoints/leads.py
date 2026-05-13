"""Public lead capture endpoint."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from app.core.deps import get_db
from app.core.limiter import limiter
from app.models.lead import Lead
from app.schemas.lead import LeadCreateIn, LeadCreateOut
from app.services.lead_scoring import calculate_lead_score
from app.services.tracking_service import emit_event
from app.services.geoip import extract_client_ip, lookup as geo_lookup

router = APIRouter()


@router.post("", response_model=LeadCreateOut, status_code=201)
@limiter.limit("3/minute")
def submit_lead(payload: LeadCreateIn, request: Request,
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
    return LeadCreateOut(id=lead.id, message="Thanks — we'll be in touch shortly.")
