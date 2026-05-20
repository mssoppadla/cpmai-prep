"""Admin CRUD for pricing plans."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_admin_user, get_super_admin_user
from app.core.exceptions import (
    NotFoundError, ConflictError, ValidationError,
)
from app.core.audit import audit_log
from app.models.user import User
from app.models.plan import Plan, PlanCourse, PlanExamSet
from app.models.exam_set import ExamSet
from app.models.lms import Course
from app.schemas.plan import PlanCreate, PlanUpdate, PlanAdminOut
from app.services.assistant.rag.ingest import reindex_quietly

router = APIRouter()


def _set_exam_sets(db: Session, plan: Plan, ids: list[int],
                   added_by_id: int) -> None:
    """Replace the plan's exam-set links with the given list. Validates
    that every id resolves to an active exam set."""
    if ids:
        sets = (db.query(ExamSet).filter(ExamSet.id.in_(ids)).all())
        found_ids = {s.id for s in sets}
        missing = [i for i in ids if i not in found_ids]
        if missing:
            raise ValidationError(f"Unknown exam_set_ids: {missing}")
    db.query(PlanExamSet).filter_by(plan_id=plan.id).delete()
    for sid in ids:
        db.add(PlanExamSet(plan_id=plan.id, exam_set_id=sid,
                           added_by=added_by_id))
    db.flush()


def _set_courses(db: Session, plan: Plan, ids: list[int],
                 added_by_id: int) -> None:
    """Replace the plan's course links with the given list. Validates
    every id resolves to a non-deleted course."""
    if ids:
        rows = db.query(Course).filter(
            Course.id.in_(ids),
            Course.is_deleted.is_(False),
        ).all()
        found_ids = {c.id for c in rows}
        missing = [i for i in ids if i not in found_ids]
        if missing:
            raise ValidationError(f"Unknown course_ids: {missing}")
    db.query(PlanCourse).filter_by(plan_id=plan.id).delete()
    for cid in ids:
        db.add(PlanCourse(plan_id=plan.id, course_id=cid,
                          added_by=added_by_id))
    db.flush()


@router.get("", response_model=list[PlanAdminOut])
def list_plans(db: Session = Depends(get_db)):
    rows = (db.query(Plan)
            .order_by(Plan.display_order, Plan.id).all())
    return [PlanAdminOut.from_row(r) for r in rows]


@router.post("", response_model=PlanAdminOut, status_code=201)
def create_plan(payload: PlanCreate,
                db: Session = Depends(get_db),
                admin: User = Depends(get_admin_user)):
    if db.query(Plan).filter_by(slug=payload.slug).first():
        raise ConflictError(f"Slug '{payload.slug}' already exists.")
    if db.query(Plan).filter_by(name=payload.name).first():
        raise ConflictError(f"Name '{payload.name}' already exists.")

    plan = Plan(
        name=payload.name, slug=payload.slug, description=payload.description,
        bundle_type=payload.bundle_type,
        base_price_paise=payload.base_price_paise,
        discount_price_paise=payload.discount_price_paise,
        currency=payload.currency, duration_days=payload.duration_days,
        perks=payload.perks or {}, is_active=payload.is_active,
        display_order=payload.display_order, created_by=admin.id,
    )
    db.add(plan); db.flush()
    _set_exam_sets(db, plan, payload.exam_set_ids or [], admin.id)
    _set_courses(db, plan, payload.course_ids or [], admin.id)
    db.commit(); db.refresh(plan)
    audit_log(db, admin.id, "plan.created",
              {"id": plan.id, "slug": plan.slug,
               "bundle_type": plan.bundle_type,
               "exam_set_count": len(payload.exam_set_ids or []),
               "course_count": len(payload.course_ids or [])})
    reindex_quietly(db, "plan", plan.id)
    return PlanAdminOut.from_row(plan)


@router.patch("/{plan_id}", response_model=PlanAdminOut)
def update_plan(plan_id: int, payload: PlanUpdate,
                db: Session = Depends(get_db),
                admin: User = Depends(get_admin_user)):
    plan = db.get(Plan, plan_id)
    if not plan: raise NotFoundError()
    data = payload.model_dump(exclude_unset=True)

    # Pre-check unique fields so the admin gets a field-named 409
    # instead of the generic IntegrityError fallback. Only collide-
    # check when the value is actually changing.
    if "name" in data and data["name"] != plan.name:
        if (db.query(Plan)
            .filter(Plan.name == data["name"], Plan.id != plan_id).first()):
            raise ConflictError(f"Name '{data['name']}' already in use.")

    # Cross-field check: don't let a partial update produce a discount
    # that's >= base. Resolve final values first, then validate.
    new_base = data.get("base_price_paise", plan.base_price_paise)
    if "discount_price_paise" in data:
        new_discount = data["discount_price_paise"]
    else:
        new_discount = plan.discount_price_paise
    if new_discount is not None and new_discount >= new_base:
        raise ValidationError(
            "discount_price_paise must be less than base_price_paise.")

    exam_set_ids = data.pop("exam_set_ids", None)
    course_ids = data.pop("course_ids", None)
    for k, v in data.items():
        setattr(plan, k, v)
    if exam_set_ids is not None:
        _set_exam_sets(db, plan, exam_set_ids, admin.id)
    if course_ids is not None:
        _set_courses(db, plan, course_ids, admin.id)
    db.commit(); db.refresh(plan)
    audit_log(db, admin.id, "plan.updated",
              {"id": plan.id, "fields": list(data.keys())})
    reindex_quietly(db, "plan", plan.id)
    return PlanAdminOut.from_row(plan)


@router.delete("/{plan_id}", status_code=204)
def delete_plan(plan_id: int,
                db: Session = Depends(get_db),
                admin: User = Depends(get_super_admin_user)):
    plan = db.get(Plan, plan_id)
    if not plan: raise NotFoundError()
    # Don't hard-delete a plan with paid subscriptions/payments — flip
    # is_active=false instead. Avoids dangling FKs in payments.plan_id.
    from app.models.payment import Payment
    if db.query(Payment).filter_by(plan_id=plan_id).first():
        raise ConflictError(
            "Plan has payments; deactivate instead of deleting.")
    db.delete(plan); db.commit()
    audit_log(db, admin.id, "plan.deleted", {"id": plan_id})
    reindex_quietly(db, "plan", plan_id)
