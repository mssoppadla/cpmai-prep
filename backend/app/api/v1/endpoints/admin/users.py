from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_super_admin_user
from app.core.exceptions import NotFoundError
from app.core.audit import audit_log
from app.models.user import User, UserRole
from app.schemas.auth import UserAdminOut

router = APIRouter()


@router.get("", response_model=list[UserAdminOut])
def list_users(db: Session = Depends(get_db),
               q: str | None = None, limit: int = Query(50, le=200),
               offset: int = 0):
    query = db.query(User)
    if q:
        query = query.filter(User.email.ilike(f"%{q}%"))
    return query.order_by(User.id.desc()).offset(offset).limit(limit).all()


@router.get("/{user_id}", response_model=UserAdminOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u: raise NotFoundError()
    return u


@router.patch("/{user_id}/role", response_model=UserAdminOut)
def change_role(user_id: int, role: UserRole,
                db: Session = Depends(get_db),
                admin: User = Depends(get_super_admin_user)):
    u = db.get(User, user_id)
    if not u: raise NotFoundError()
    old = u.role
    u.role = role
    db.commit(); db.refresh(u)
    audit_log(db, admin.id, "user.role_changed",
              {"target_user_id": user_id, "from": old.value, "to": role.value})
    return u
