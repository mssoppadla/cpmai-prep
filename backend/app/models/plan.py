"""Pricing plans + their exam-set bundling.

Admin-managed; activated/deactivated without code change. Concept hierarchy:

  - Plan          → a sellable item (exam bundle, course bundle, etc.).
                    Admin sets base + optional discount price; one-time
                    purchase grants a 1-year subscription.
  - PlanExamSet   → which exam sets the plan unlocks. Many-to-many.
  - Plan.perks    → free-form JSON for non-exam unlocks (course Zoom URL,
                    extras). Kept untyped on purpose so future bundles
                    can ship without a schema migration.

Subscription rows hold the resolved access state at purchase time
(user_id, plan_id, expires_at, status). Paywall checks join through
plan_exam_sets to decide whether a given exam set is unlocked.
"""
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, JSON, DateTime,
    ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Plan(Base):
    __tablename__ = "plans"

    id                   = Column(Integer, primary_key=True)
    name                 = Column(String(120), unique=True, nullable=False)
    slug                 = Column(String(140), unique=True, nullable=False, index=True)
    description          = Column(Text)
    bundle_type          = Column(String(32), nullable=False)
    # ^ "exam_bundle" | "course_bundle" | "custom" — free-form, validated at
    #   the schema layer so admins can introduce new categories without an
    #   enum migration.

    base_price_paise     = Column(Integer, nullable=False)
    discount_price_paise = Column(Integer)              # NULL = no discount
    currency             = Column(String(8), nullable=False, default="INR")
    duration_days        = Column(Integer, nullable=False, default=365)

    perks                = Column(JSON, default=dict)   # {course_zoom_url, ...}
    is_active            = Column(Boolean, default=True, nullable=False, index=True)
    display_order        = Column(Integer, default=100, nullable=False)

    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())

    exam_sets = relationship(
        "ExamSet", secondary="plan_exam_sets", lazy="selectin",
    )


class PlanExamSet(Base):
    __tablename__ = "plan_exam_sets"
    __table_args__ = (
        UniqueConstraint("plan_id", "exam_set_id", name="uq_plan_exam_set"),
        Index("ix_plan_exam_sets_plan", "plan_id"),
        Index("ix_plan_exam_sets_set", "exam_set_id"),
    )

    plan_id     = Column(Integer, ForeignKey("plans.id", ondelete="CASCADE"),
                         primary_key=True)
    exam_set_id = Column(Integer, ForeignKey("exam_sets.id", ondelete="CASCADE"),
                         primary_key=True)
    added_at    = Column(DateTime(timezone=True), server_default=func.now())
    added_by    = Column(Integer, ForeignKey("users.id"))
