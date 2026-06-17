"""Email-template schemas — admin CRUD + test-send."""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class EmailTemplateCreate(BaseModel):
    # NULL/empty source = the default fallback template. Stored as NULL.
    source: Optional[str] = Field(default=None, max_length=64)
    subject: str = Field(min_length=1, max_length=240)
    html_body: str = Field(min_length=1)
    is_active: bool = True

    @field_validator("source")
    @classmethod
    def _empty_source_is_default(cls, v):
        # Treat "" and whitespace as "the default template" (NULL) so the
        # admin UI's empty selector maps cleanly to the fallback row.
        if v is None:
            return None
        v = v.strip()
        return v or None


class EmailTemplateUpdate(BaseModel):
    source: Optional[str] = Field(default=None, max_length=64)
    subject: Optional[str] = Field(default=None, min_length=1, max_length=240)
    html_body: Optional[str] = Field(default=None, min_length=1)
    is_active: Optional[bool] = None


class EmailTemplateOut(BaseModel):
    id: int
    source: Optional[str]
    subject: str
    html_body: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EmailTemplateTestIn(BaseModel):
    """Optional override recipient for the test send. Defaults to the
    requesting admin's own email when omitted."""
    to: Optional[str] = Field(default=None, max_length=240)
