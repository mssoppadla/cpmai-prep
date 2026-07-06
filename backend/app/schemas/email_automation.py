"""Email-automation schemas — admin CRUD, outbox activity, test/bulk send.

Contract: docs/contracts/email-automation.md
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.email_automation import SEND_POLICIES


class AttachmentIn(BaseModel):
    """Exactly the shape /admin/uploads returns — stored verbatim."""
    url: str = Field(min_length=1, max_length=500)
    filename: str = Field(min_length=1, max_length=200)
    mime_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(ge=0)

    @field_validator("url")
    @classmethod
    def _must_be_upload_url(cls, v: str) -> str:
        if not v.startswith("/uploads/"):
            raise ValueError("attachment url must start with /uploads/")
        return v


class ConditionIn(BaseModel):
    """One predicate row. ``type`` is validated against the code catalog
    at the endpoint (needs the registry import); params are free-form
    here and validated per-type there."""
    type: str = Field(min_length=1, max_length=64)

    model_config = {"extra": "allow"}


class EmailAutomationBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    trigger_key: str = Field(min_length=1, max_length=64)
    conditions: list[ConditionIn] = Field(default_factory=list,
                                          max_length=10)
    delay_minutes: int = Field(default=0, ge=0, le=60 * 24 * 90)  # ≤90 days
    subject: str = Field(min_length=1, max_length=240)
    html_body: str = Field(min_length=1)
    attachments: list[AttachmentIn] = Field(default_factory=list,
                                            max_length=10)
    send_policy: str = Field(default="once_per_user")
    cooldown_days: int = Field(default=0, ge=0, le=365)
    is_active: bool = False
    # Mail types sharing a group suppress each other per recipient email
    # (first-sent-wins). ""/None = no suppression.
    suppression_group: Optional[str] = Field(default=None, max_length=64)

    @field_validator("send_policy")
    @classmethod
    def _known_policy(cls, v: str) -> str:
        if v not in SEND_POLICIES:
            raise ValueError(f"send_policy must be one of {SEND_POLICIES}")
        return v

    @field_validator("suppression_group")
    @classmethod
    def _blank_group_is_none(cls, v):
        if v is None:
            return None
        v = v.strip()
        return v or None


class EmailAutomationCreate(EmailAutomationBase):
    pass


class EmailAutomationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    trigger_key: Optional[str] = Field(default=None, min_length=1,
                                       max_length=64)
    conditions: Optional[list[ConditionIn]] = Field(default=None,
                                                    max_length=10)
    delay_minutes: Optional[int] = Field(default=None, ge=0,
                                         le=60 * 24 * 90)
    subject: Optional[str] = Field(default=None, min_length=1,
                                   max_length=240)
    html_body: Optional[str] = Field(default=None, min_length=1)
    attachments: Optional[list[AttachmentIn]] = Field(default=None,
                                                      max_length=10)
    send_policy: Optional[str] = None
    cooldown_days: Optional[int] = Field(default=None, ge=0, le=365)
    is_active: Optional[bool] = None
    suppression_group: Optional[str] = Field(default=None, max_length=64)

    @field_validator("send_policy")
    @classmethod
    def _known_policy(cls, v):
        if v is not None and v not in SEND_POLICIES:
            raise ValueError(f"send_policy must be one of {SEND_POLICIES}")
        return v

    @field_validator("suppression_group")
    @classmethod
    def _blank_group_is_none(cls, v):
        if v is None:
            return None
        v = v.strip()
        return v or None


class EmailAutomationOut(BaseModel):
    id: int
    name: str
    trigger_key: str
    conditions: list
    delay_minutes: int
    subject: str
    html_body: str
    attachments: list
    send_policy: str
    cooldown_days: int
    is_active: bool
    suppression_group: Optional[str] = None
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class OutboxRowOut(BaseModel):
    """Activity-tab row — the admin's proof of whether a mail went out."""
    id: int
    automation_id: Optional[int]
    automation_name: Optional[str] = None   # joined label (survives delete)
    # Recipient: user_id for account holders, lead_id for landing-form
    # leads (lead.captured) — exactly one is set.
    user_id: Optional[int] = None
    lead_id: Optional[int] = None
    # Populated by the endpoint from the joined User/Lead row (the ORM
    # outbox object itself has no user_email attribute).
    user_email: str = ""
    to_email: str
    status: str
    source: str
    scheduled_at: Optional[datetime]
    sent_at: Optional[datetime]
    attempts: int
    last_error: Optional[str]
    skip_reason: Optional[str]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class OutboxPageOut(BaseModel):
    total: int
    items: list[OutboxRowOut]


class TestSendIn(BaseModel):
    """Test a specific automation's template — sends to the requesting
    admin (or an override recipient) with sample placeholder values."""
    to: Optional[str] = Field(default=None, max_length=240)


class SmtpTestIn(BaseModel):
    """Raw SMTP connectivity test for the Email Account tab."""
    to: Optional[str] = Field(default=None, max_length=240)


class SmtpTestOut(BaseModel):
    ok: bool
    to: str
    # The REAL failure ('authentication failed', 'connection refused',
    # …) — the whole point of this endpoint vs the fail-soft mailer.
    error: Optional[str] = None


class BulkSendIn(BaseModel):
    """Manual bulk send (Users page). Conditions are not applied —
    the admin explicitly picked the recipients."""
    user_ids: list[int] = Field(min_length=1, max_length=500)


class BulkSendOut(BaseModel):
    queued: int
    skipped: list[dict]   # [{user_id, reason}] — deleted user, no email…
