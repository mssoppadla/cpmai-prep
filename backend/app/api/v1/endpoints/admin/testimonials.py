"""Admin testimonial CRUD — drives the landing-page carousel."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import NotFoundError
from app.models.testimonial import Testimonial
from app.models.user import User
from app.schemas.testimonial import TestimonialAdminOut, TestimonialIn

router = APIRouter()


@router.get("", response_model=list[TestimonialAdminOut])
def list_testimonials(db: Session = Depends(get_db),
                      limit: int = Query(200, le=500), offset: int = 0):
    return (db.query(Testimonial)
            .order_by(Testimonial.display_order, Testimonial.id)
            .offset(offset).limit(limit).all())


@router.post("", response_model=TestimonialAdminOut, status_code=201)
def create_testimonial(payload: TestimonialIn,
                       db: Session = Depends(get_db),
                       admin: User = Depends(get_admin_user)):
    t = Testimonial(**payload.model_dump())
    db.add(t); db.commit(); db.refresh(t)
    audit_log(db, admin.id, "testimonial.created", {"id": t.id})
    return t


@router.patch("/{testimonial_id}", response_model=TestimonialAdminOut)
def update_testimonial(testimonial_id: int, payload: TestimonialIn,
                       db: Session = Depends(get_db),
                       admin: User = Depends(get_admin_user)):
    t = db.get(Testimonial, testimonial_id)
    if not t:
        raise NotFoundError()
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    db.commit(); db.refresh(t)
    audit_log(db, admin.id, "testimonial.updated", {"id": t.id})
    return t


@router.delete("/{testimonial_id}", status_code=204)
def delete_testimonial(testimonial_id: int,
                       db: Session = Depends(get_db),
                       admin: User = Depends(get_admin_user)):
    t = db.get(Testimonial, testimonial_id)
    if not t:
        raise NotFoundError()
    db.delete(t); db.commit()
    audit_log(db, admin.id, "testimonial.deleted", {"id": testimonial_id})
