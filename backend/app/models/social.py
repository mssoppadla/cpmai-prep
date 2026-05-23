"""SQLAlchemy models for social automation: campaigns + campaign_runs.

Schema: backend/migrations/versions/0031_social_campaigns.py

Models use generic ``sa.JSON`` (not postgresql.JSONB) so SQLite-based
unit tests can build the schema via Base.metadata.create_all(); the
prod migration uses JSONB for better indexing.
"""
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Campaign(Base):
    """A scheduled, named, repeatable AI-content workflow."""
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_campaigns_tenant_name"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer,
                       ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    name = Column(String(120), nullable=False)
    description = Column(Text)
    # Validated against app.services.social.runners.WORKFLOWS at write time.
    workflow_type = Column(String(64), nullable=False)
    # 5-field cron. NULL = manual run only.
    schedule_cron = Column(String(120))
    # Workflow-specific config. Shape is workflow-defined; runner
    # classes document their expected keys.
    config_json = Column(JSON, nullable=False, default=dict)
    active = Column(Boolean, nullable=False, default=True)

    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)

    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))

    runs = relationship(
        "CampaignRun",
        back_populates="campaign",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class CampaignRun(Base):
    """One execution of a Campaign — either scheduled or manual."""
    __tablename__ = "campaign_runs"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer,
                       ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    campaign_id = Column(Integer,
                         ForeignKey("campaigns.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    started_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    status = Column(String(16), nullable=False, default="queued")
    generated_content = Column(Text)
    posted_at = Column(DateTime(timezone=True))
    posted_to_platforms = Column(JSON, nullable=False, default=list)
    error = Column(Text)

    campaign = relationship("Campaign", back_populates="runs")
