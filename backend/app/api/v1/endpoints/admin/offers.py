"""Admin CRUD for offer codes (discount coupons)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_admin_user, get_super_admin_user
from app.core.exceptions import NotFoundError, ConflictError
from app.core.audit import audit_log
from app.models.user import User
from app.models.offer import OfferCode, OfferRedemption
from app.schemas.offer import (
    OfferCodeCreate, OfferCodeUpdate, OfferCodeAdminOut,
)

router = APIRouter()


@router.get("", response_model=list[OfferCodeAdminOut])
def list_codes(db: Session = Depends(get_db)):
    rows = db.query(OfferCode).order_by(OfferCode.id.desc()).all()
    return rows


@router.post("", response_model=OfferCodeAdminOut, status_code=201)
def create_code(payload: OfferCodeCreate,
                db: Session = Depends(get_db),
                admin: User = Depends(get_admin_user)):
    if db.query(OfferCode).filter_by(code=payload.code).first():
        raise ConflictError(f"Code '{payload.code}' already exists.")
    row = OfferCode(
        code=payload.code,
        description=payload.description,
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        max_redemptions=payload.max_redemptions,
        applies_to_plan_ids=payload.applies_to_plan_ids,
        is_active=payload.is_active,
        created_by=admin.id,
    )
    db.add(row); db.commit(); db.refresh(row)
    audit_log(db, admin.id, "offer.created",
              {"id": row.id, "code": row.code,
               "type": row.discount_type, "value": row.discount_value})
    return row


@router.patch("/{code_id}", response_model=OfferCodeAdminOut)
def update_code(code_id: int, payload: OfferCodeUpdate,
                db: Session = Depends(get_db),
                admin: User = Depends(get_admin_user)):
    row = db.get(OfferCode, code_id)
    if not row: raise NotFoundError()
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    db.commit(); db.refresh(row)
    audit_log(db, admin.id, "offer.updated",
              {"id": code_id, "fields": list(data.keys())})
    return row


@router.delete("/{code_id}", status_code=204)
def delete_code(code_id: int,
                db: Session = Depends(get_db),
                admin: User = Depends(get_super_admin_user)):
    row = db.get(OfferCode, code_id)
    if not row: raise NotFoundError()
    # Block hard-delete if redemptions exist — preserves audit trail.
    if db.query(OfferRedemption).filter_by(offer_code_id=code_id).first():
        raise ConflictError(
            "Code has redemptions; deactivate instead of deleting.")
    db.delete(row); db.commit()
    audit_log(db, admin.id, "offer.deleted", {"id": code_id})
