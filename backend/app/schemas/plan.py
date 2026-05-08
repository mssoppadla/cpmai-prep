"""Plan schemas — admin CRUD + public read.

Server is the source of truth for `final_price_paise`. The admin form
sets `base_price_paise` and optional `discount_price_paise`; everything
downstream computes from those.
"""
from typing import Literal, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


BundleType = Literal["exam_bundle", "course_bundle", "custom"]


# ============================================================ admin in
class PlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=140,
                      pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: Optional[str] = None
    bundle_type: BundleType = "exam_bundle"
    base_price_paise: int = Field(ge=100)                 # min ₹1
    discount_price_paise: Optional[int] = Field(default=None, ge=0)
    currency: str = Field(default="INR", max_length=8)
    duration_days: int = Field(default=365, ge=1, le=3650)
    perks: dict = Field(default_factory=dict)
    is_active: bool = True
    display_order: int = 100
    exam_set_ids: list[int] = Field(default_factory=list)

    @field_validator("discount_price_paise")
    @classmethod
    def _discount_lt_base(cls, v, info):
        # base_price_paise is validated first because it's listed first
        # in the model — it's available as info.data["base_price_paise"]
        # by the time this validator runs.
        if v is None:
            return v
        base = info.data.get("base_price_paise")
        if base is not None and v >= base:
            raise ValueError("discount_price_paise must be less than "
                             "base_price_paise")
        return v


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    bundle_type: Optional[BundleType] = None
    base_price_paise: Optional[int] = Field(default=None, ge=100)
    discount_price_paise: Optional[int] = Field(default=None, ge=0)
    duration_days: Optional[int] = Field(default=None, ge=1, le=3650)
    perks: Optional[dict] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None
    exam_set_ids: Optional[list[int]] = None


# =========================================================== admin out
class PlanExamSetRef(BaseModel):
    id: int
    slug: str
    name: str


class PlanAdminOut(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str]
    bundle_type: str
    base_price_paise: int
    discount_price_paise: Optional[int]
    currency: str
    duration_days: int
    perks: dict
    is_active: bool
    display_order: int
    exam_sets: list[PlanExamSetRef]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row) -> "PlanAdminOut":
        return cls(
            id=row.id, name=row.name, slug=row.slug,
            description=row.description, bundle_type=row.bundle_type,
            base_price_paise=row.base_price_paise,
            discount_price_paise=row.discount_price_paise,
            currency=row.currency, duration_days=row.duration_days,
            perks=row.perks or {}, is_active=row.is_active,
            display_order=row.display_order,
            exam_sets=[PlanExamSetRef(id=es.id, slug=es.slug, name=es.name)
                       for es in (row.exam_sets or [])],
            created_at=row.created_at, updated_at=row.updated_at,
        )


# ================================================ public-read shape
class PlanPublicOut(BaseModel):
    """Shown on the marketing /pricing page. Same fields as admin but
    we drop audit metadata (display_order, timestamps)."""
    id: int
    name: str
    slug: str
    description: Optional[str]
    bundle_type: str
    base_price_paise: int
    discount_price_paise: Optional[int]
    currency: str
    duration_days: int
    perks: dict
    exam_sets: list[PlanExamSetRef]

    @classmethod
    def from_row(cls, row) -> "PlanPublicOut":
        return cls(
            id=row.id, name=row.name, slug=row.slug,
            description=row.description, bundle_type=row.bundle_type,
            base_price_paise=row.base_price_paise,
            discount_price_paise=row.discount_price_paise,
            currency=row.currency, duration_days=row.duration_days,
            perks=row.perks or {},
            exam_sets=[PlanExamSetRef(id=es.id, slug=es.slug, name=es.name)
                       for es in (row.exam_sets or [])],
        )
