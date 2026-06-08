"""User-or-anonymous endpoints for an in-flight or submitted attempt.

Both signed-in users and anonymous browser sessions (X-Anon-Token header)
can drive these endpoints. Ownership is enforced inside the service against
either session.user_id or session.anon_token — see ExamService._load_session.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_actor, get_current_user
from app.models.user import User
from app.schemas.exam import (
    ExamAttemptOut, AnswerIn, SubmitAttemptOut, AttemptHistoryOut,
)
from app.services.exam_service import ExamService

router = APIRouter()


# Declared before "/attempts/{attempt_id}" so the literal path wins cleanly.
@router.get("/attempts", response_model=list[AttemptHistoryOut])
def list_my_attempts(db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """The signed-in learner's exam history — their submitted attempts,
    newest first. Each links back to the full results screen (by-domain
    breakdown + review) via its `id`. Requires a signed-in account."""
    return ExamService(db).list_attempts(user)


@router.get("/attempts/{attempt_id}", response_model=ExamAttemptOut)
def get_attempt(attempt_id: int, db: Session = Depends(get_db),
                actor=Depends(get_actor)):
    return ExamService(db).get_attempt(actor, attempt_id)


@router.patch("/attempts/{attempt_id}/answer", status_code=204)
def save_answer(attempt_id: int, payload: AnswerIn,
                db: Session = Depends(get_db),
                actor=Depends(get_actor)):
    ExamService(db).save_answer(actor, attempt_id, payload)


@router.post("/attempts/{attempt_id}/submit", response_model=SubmitAttemptOut)
def submit_attempt(attempt_id: int, db: Session = Depends(get_db),
                   actor=Depends(get_actor)):
    return ExamService(db).submit(actor, attempt_id)


@router.get("/attempts/{attempt_id}/result", response_model=SubmitAttemptOut)
def get_attempt_result(attempt_id: int, db: Session = Depends(get_db),
                       actor=Depends(get_actor)):
    """Cold-load a submitted attempt's full result (with per-option reasoning)."""
    return ExamService(db).get_result(actor, attempt_id)

