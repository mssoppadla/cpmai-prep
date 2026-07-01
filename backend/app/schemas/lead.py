from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, EmailStr
from app.models.lead import LeadSource


class UtmIn(BaseModel):
    source: str | None = None
    medium: str | None = None
    campaign: str | None = None
    term: str | None = None
    content: str | None = None


class LeadCreateIn(BaseModel):
    email: EmailStr
    name: str | None = None
    phone: str | None = None
    # WhatsApp opt-in (community lead magnet)
    country_code: str | None = None        # e.g. "+91"
    whatsapp_number: str | None = None     # local part
    linkedin_id: str | None = None         # LinkedIn id/URL (serve better + share docs)
    company: str | None = None
    role: str | None = None
    source: LeadSource
    landing_url: str | None = None
    utm: UtmIn | None = None
    interests: list[str] = []
    target_exam_date: date | None = None
    experience_level: str | None = None
    consent_marketing: bool = False


class LeadCreateOut(BaseModel):
    id: int
    message: str


class LeadAdminOut(BaseModel):
    id: int
    email: str
    name: str | None
    phone: str | None
    linkedin_id: str | None = None
    source: LeadSource
    utm_source: str | None
    utm_campaign: str | None
    target_exam_date: date | None
    consent_marketing: bool
    converted_user_id: int | None
    # 0..100 rule-based score, populated at insert time and on any
    # notes-patch save. `null` for leads that pre-date the feature.
    score: int | None = None
    # GeoIP enrichment (PR-A). `country` is ISO-3166-1 alpha-2 (e.g.
    # "IN"); frontend renders it as a flag emoji + city.
    country: str | None = None
    city: str | None = None
    class Config: from_attributes = True


# Unified contacts feed: leads (landing-form submissions) + users
# (signed up via password or Google) in one row stream.
class ContactRow(BaseModel):
    """Discriminated row in the /admin/contacts feed.

    `kind` distinguishes the underlying source. Common fields are flattened
    so the admin UI can render a single table.
    """
    kind: Literal["lead", "user"]
    id: int                      # row id within its own table (lead.id or user.id)
    email: str
    name: str | None = None
    created_at: datetime

    # Lead-specific (None for users)
    source: str | None = None    # LeadSource value
    linkedin_id: str | None = None   # LinkedIn id/URL left on the landing form
    utm_campaign: str | None = None
    consent_marketing: bool | None = None
    notes: str | None = None
    converted_user_id: int | None = None
    target_exam_date: date | None = None
    # Rule-based score in 0..100 for lead rows. `None` for user rows
    # AND for legacy lead rows that pre-date the scoring feature. UI
    # renders HOT/WARM/COLD chips based on the bucket.
    score: int | None = None
    # GeoIP enrichment (PR-A). Only set on lead rows. `country` is
    # ISO-3166-1 alpha-2 (frontend → flag emoji); `city` is English
    # transliteration. `None` for users and for legacy/private-IP leads.
    country: str | None = None
    city: str | None = None

    # User-specific (None for leads)
    role: str | None = None
    has_google: bool | None = None
    has_password: bool | None = None
    has_active_subscription: bool | None = None
    last_login_at: datetime | None = None
    # Non-null after the user has been soft-deleted (via GDPR self-
    # service OR admin delete). UI dims the row and shows a small
    # "deleted" badge so operators don't mistake them for active
    # accounts. The redacted email pattern (deleted-{id}@redacted.invalid)
    # is also visible, but having a dedicated field lets the UI mark
    # the row without string-sniffing.
    deleted_at: datetime | None = None
