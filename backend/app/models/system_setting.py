from sqlalchemy import Column, String, JSON, Text, Integer, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key         = Column(String(80), primary_key=True)
    value       = Column(JSON, nullable=False)
    description = Column(Text)
    updated_by  = Column(Integer, ForeignKey("users.id"))
    updated_at  = Column(DateTime(timezone=True),
                         server_default=func.now(), onupdate=func.now())
