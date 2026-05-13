from sqlalchemy import Column, String, JSON, Text, Integer, Boolean, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key         = Column(String(80), primary_key=True)
    value       = Column(JSON, nullable=False)
    description = Column(Text)
    # ``is_secret`` flips the /admin/settings GET response from echoing
    # the raw value to masking it as ``"••••last4"``. PATCH still accepts
    # plaintext (the masked value isn't itself meaningful — admins always
    # paste the full new value). Default FALSE so existing rows behave
    # as before. Migration 0019 added this column.
    is_secret   = Column(Boolean, nullable=False, default=False,
                         server_default="false")
    updated_by  = Column(Integer, ForeignKey("users.id"))
    updated_at  = Column(DateTime(timezone=True),
                         server_default=func.now(), onupdate=func.now())
