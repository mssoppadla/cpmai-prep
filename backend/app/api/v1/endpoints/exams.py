"""Authenticated user endpoints for an in-flight or submitted attempt."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.exam import ExamAttemptOut, AnswerIn, SubmitAttemptOut
from app.services.exam_service import ExamService

router = APIRouter()


@router.get("/attempts/{attempt_id}", response_model=ExamAttemptOut)
def get_attempt(attempt_id: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    return ExamService(db).get_attempt(user, attempt_id)


@router.patch("/attempts/{attempt_id}/answer", status_code=204)
def save_answer(attempt_id: int, payload: AnswerIn,
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    ExamService(db).save_answer(user, attempt_id, payload)


@router.post("/attempts/{attempt_id}/submit", response_model=SubmitAttemptOut)
def submit_attempt(attempt_id: int, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    return ExamService(db).submit(user, attempt_id)
