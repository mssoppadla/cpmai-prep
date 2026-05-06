from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_current_user
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.auth import (
    SubscriptionSummary, UserDashboardOut, UserOut,
)

router = APIRouter()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/me/dashboard", response_model=UserDashboardOut)
def my_dashboard(user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Self-view for the learner home page.

    Bundles user identity + subscription state in one round-trip so the
    dashboard can render without a second fetch. Active subscription is
    the most recent row with status='active' (the model allows multiple
    rows over time as plans change).
    """
    sub = (db.query(Subscription)
           .filter_by(user_id=user.id, status="active")
           .order_by(Subscription.created_at.desc()).first())
    return UserDashboardOut(
        user=UserOut.model_validate(user),
        subscription=SubscriptionSummary(
            active=bool(sub),
            plan=sub.plan if sub else None,
            status=sub.status if sub else None,
            current_period_end=sub.current_period_end if sub else None,
        ),
        has_google=bool(user.google_id),
        has_password=bool(user.password_hash),
    )
