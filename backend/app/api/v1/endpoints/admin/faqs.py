"""Admin FAQ CRUD — drives the FAQ section on the public landing page."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import NotFoundError
from app.models.faq import FaqItem
from app.models.user import User
from app.schemas.faq import FaqAdminOut, FaqIn

router = APIRouter()


@router.get("", response_model=list[FaqAdminOut])
def list_faqs(db: Session = Depends(get_db),
              limit: int = Query(200, le=500), offset: int = 0):
    return (db.query(FaqItem)
            .order_by(FaqItem.display_order, FaqItem.id)
            .offset(offset).limit(limit).all())


@router.post("", response_model=FaqAdminOut, status_code=201)
def create_faq(payload: FaqIn,
               db: Session = Depends(get_db),
               admin: User = Depends(get_admin_user)):
    f = FaqItem(**payload.model_dump())
    db.add(f); db.commit(); db.refresh(f)
    audit_log(db, admin.id, "faq.created", {"id": f.id})
    return f


@router.patch("/{faq_id}", response_model=FaqAdminOut)
def update_faq(faq_id: int, payload: FaqIn,
               db: Session = Depends(get_db),
               admin: User = Depends(get_admin_user)):
    f = db.get(FaqItem, faq_id)
    if not f:
        raise NotFoundError()
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(f, k, v)
    db.commit(); db.refresh(f)
    audit_log(db, admin.id, "faq.updated", {"id": f.id})
    return f


@router.delete("/{faq_id}", status_code=204)
def delete_faq(faq_id: int,
               db: Session = Depends(get_db),
               admin: User = Depends(get_admin_user)):
    f = db.get(FaqItem, faq_id)
    if not f:
        raise NotFoundError()
    db.delete(f); db.commit()
    audit_log(db, admin.id, "faq.deleted", {"id": faq_id})
