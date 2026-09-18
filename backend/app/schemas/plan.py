"""Plan schemas — admin CRUD + public read.

Server is the source of truth for `final_price_paise`. The admin form
sets `base_price_paise` and optional `discount_price_paise`; everything
downstream computes from those.
"""
from typing import Literal, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from app.core.labs_registry import LAB_BY_SLUG, PERK_LABS_KEY, normalise_perk_labs


BundleType = Literal["exam_bundle", "course_bundle", "custom"]


def _check_perk_labs(perks: dict | None) -> dict | None:
    """perks["labs"] must be a list of registered lab slugs. Unknown
    slugs are a 422 on WRITE (typo protection) even though reads drop
    them silently."""
    if perks is None:
        return perks
    raw = perks.get(PERK_LABS_KEY)
    if raw is None:
        return perks
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ValueError('perks.labs must be a list of lab slugs')
    unknown = sorted(set(raw) - set(LAB_BY_SLUG))
    if unknown:
        raise ValueError(f"unknown lab slug(s): {', '.join(unknown)}")
    perks[PERK_LABS_KEY] = normalise_perk_labs(perks)
    return perks


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
    course_ids: list[int] = Field(default_factory=list)

    @field_validator("perks")
    @classmethod
    def _perks_labs(cls, v):
        return _check_perk_labs(v)

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
    course_ids: Optional[list[int]] = None

    @field_validator("perks")
    @classmethod
    def _perks_labs(cls, v):
        return _check_perk_labs(v)


# =========================================================== admin out
class PlanExamSetRef(BaseModel):
    id: int
    slug: str
    name: str


class PlanCourseRef(BaseModel):
    id: int
    slug: str
    title: str


class PlanLabRef(BaseModel):
    """A lab the plan unlocks (from perks["labs"], resolved against the
    registry so the UI can print a title without a second lookup)."""
    slug: str
    title: str


def _lab_refs(row) -> list["PlanLabRef"]:
    from app.services.labs_access import lab_settings
    out = []
    for slug in normalise_perk_labs(row.perks):
        lab = LAB_BY_SLUG[slug]
        out.append(PlanLabRef(slug=slug, title=lab_settings(lab).title))
    return out


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
    courses: list[PlanCourseRef]
    labs: list[PlanLabRef]
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
            courses=[PlanCourseRef(id=c.id, slug=c.slug, title=c.title)
                     for c in (row.courses or [])
                     if not getattr(c, "is_deleted", False)],
            labs=_lab_refs(row),
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
    courses: list[PlanCourseRef]
    labs: list[PlanLabRef]

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
            courses=[PlanCourseRef(id=c.id, slug=c.slug, title=c.title)
                     for c in (row.courses or [])
                     if not getattr(c, "is_deleted", False)],
            labs=_lab_refs(row),
        )
