"""Admin exam views — read any user's attempt result (support/guidance). Admin-gated by the
router-level get_admin_user dependency, so this bypasses the per-user ownership check."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_admin_user
from app.schemas.exam import SubmitAttemptOut
from app.services.exam_service import ExamService

router = APIRouter()


@router.get("/attempts/{attempt_id}/result", response_model=SubmitAttemptOut)
def admin_get_attempt_result(attempt_id: int, db: Session = Depends(get_db),
                             admin=Depends(get_admin_user)):
    """Any user's submitted attempt result (per-question pass/fail + reasoning + domain breakdown),
    so an admin can guide the candidate on focus areas. Reuses the same result the aspirant sees."""
    return ExamService(db).get_result(admin, attempt_id, admin=True)


@router.delete("/attempts/{attempt_id}", status_code=204)
def admin_delete_attempt(attempt_id: int, db: Session = Depends(get_db),
                         admin=Depends(get_admin_user)):
    """Delete any user's attempt (answers cascade) — used from the user
    insights view to clear a broken or stale sitting on request."""
    ExamService(db).delete_attempt(admin, attempt_id, admin=True)
