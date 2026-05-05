from datetime import date
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
    source: LeadSource
    utm_source: str | None
    utm_campaign: str | None
    target_exam_date: date | None
    consent_marketing: bool
    converted_user_id: int | None
    class Config: from_attributes = True
