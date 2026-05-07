"""User-facing exam set endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_actor, get_optional_user
from app.core.exceptions import NotFoundError
from app.models.exam_set import ExamSet
from app.models.exam_session import ExamSession
from app.models.user import User
from app.schemas.exam_set import ExamSetSummaryOut
from app.schemas.exam import ExamAttemptOut
from app.services.exam_service import ExamService

router = APIRouter()


def _to_summary(es: ExamSet, user_attempts: int = 0) -> ExamSetSummaryOut:
    return ExamSetSummaryOut(
        id=es.id, name=es.name, slug=es.slug, description=es.description,
        difficulty=es.difficulty, time_limit_minutes=es.time_limit_minutes,
        passing_score=es.passing_score, is_premium=es.is_premium,
        cover_image_url=es.cover_image_url,
        question_count=len(es.questions),
        user_attempts=user_attempts,
    )


@router.get("", response_model=list[ExamSetSummaryOut])
def list_active_sets(db: Session = Depends(get_db),
                     user: User | None = Depends(get_optional_user)):
    sets = (db.query(ExamSet).filter_by(is_active=True)
            .order_by(ExamSet.display_order, ExamSet.id).all())
    if not user:
        return [_to_summary(es) for es in sets]
    counts = dict(
        db.query(ExamSession.exam_set_id, ExamSession.id)
          .filter(ExamSession.user_id == user.id, ExamSession.exam_set_id.in_(
              [s.id for s in sets])).all()
    )
    return [_to_summary(es, counts.get(es.id, 0)) for es in sets]


@router.get("/{slug}", response_model=ExamSetSummaryOut)
def get_set(slug: str, db: Session = Depends(get_db),
            user: User | None = Depends(get_optional_user)):
    es = db.query(ExamSet).filter_by(slug=slug, is_active=True).first()
    if not es:
        raise NotFoundError("Exam set not found.")
    n = 0
    if user:
        n = db.query(ExamSession).filter_by(
            user_id=user.id, exam_set_id=es.id,
        ).count()
    return _to_summary(es, n)


@router.post("/{slug}/start", response_model=ExamAttemptOut, status_code=201)
def start_attempt(slug: str, db: Session = Depends(get_db),
                  actor=Depends(get_actor)):
    """Start (or resume) an attempt.

    Accepts either a signed-in user (Bearer token) or an anonymous browser-
    bound session (X-Anon-Token header — minted client-side). Premium sets
    reject anonymous callers up front; free sets are open to either.
    """
    return ExamService(db).start_attempt(actor, slug)
