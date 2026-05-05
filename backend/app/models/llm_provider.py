from sqlalchemy import (
    Column, Integer, String, Boolean, JSON, DateTime, LargeBinary, ForeignKey
)
from sqlalchemy.sql import func
from app.core.database import Base


class LLMProviderConfig(Base):
    __tablename__ = "llm_providers"
    id                = Column(Integer, primary_key=True)
    name              = Column(String(80), unique=True, nullable=False)
    provider_type     = Column(String(32), nullable=False)
    model             = Column(String(128), nullable=False)
    api_key_encrypted = Column(LargeBinary)
    base_url          = Column(String(255))
    config            = Column(JSON, default=dict)
    is_enabled        = Column(Boolean, default=True, nullable=False, index=True)
    priority          = Column(Integer, default=100, nullable=False)
    created_by        = Column(Integer, ForeignKey("users.id"))
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    updated_at        = Column(DateTime(timezone=True),
                               server_default=func.now(), onupdate=func.now())
