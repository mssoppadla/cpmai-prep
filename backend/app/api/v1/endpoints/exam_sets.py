"""User-facing exam set endpoints."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_actor, get_optional_user
from app.core.exceptions import NotFoundError
from app.models.exam_set import ExamSet, ExamSetQuestion
from app.models.exam_session import ExamSession
from app.models.user import User
from app.schemas.exam_set import ExamSetSummaryOut
from app.schemas.exam import ExamAttemptOut
from app.services.exam_service import ExamService

router = APIRouter()


def _to_summary(es: ExamSet, user_attempts: int = 0,
                in_progress: bool = False,
                question_count: int | None = None) -> ExamSetSummaryOut:
    return ExamSetSummaryOut(
        id=es.id, name=es.name, slug=es.slug, description=es.description,
        difficulty=es.difficulty, time_limit_minutes=es.time_limit_minutes,
        passing_score=es.passing_score, is_premium=es.is_premium,
        cover_image_url=es.cover_image_url,
        # Prefer a pre-computed COUNT — len(es.questions) lazily loads
        # every question ROW of the set just to count them, on a hot
        # public endpoint (perf review 2026-08-07).
        question_count=(question_count if question_count is not None
                        else len(es.questions)),
        user_attempts=user_attempts,
        in_progress=in_progress,
    )


def _question_counts(db: Session, set_ids: list[int]) -> dict[int, int]:
    if not set_ids:
        return {}
    return dict(
        db.query(ExamSetQuestion.exam_set_id,
                 func.count(ExamSetQuestion.question_id))
          .filter(ExamSetQuestion.exam_set_id.in_(set_ids))
          .group_by(ExamSetQuestion.exam_set_id).all())


@router.get("", response_model=list[ExamSetSummaryOut])
def list_active_sets(db: Session = Depends(get_db),
                     user: User | None = Depends(get_optional_user)):
    sets = (db.query(ExamSet).filter_by(is_active=True)
            .order_by(ExamSet.display_order, ExamSet.id).all())
    qcounts = _question_counts(db, [s.id for s in sets])
    if not user:
        return [_to_summary(es, question_count=qcounts.get(es.id, 0))
                for es in sets]
    set_ids = [s.id for s in sets]
    # Was `dict(query(exam_set_id, id))` — which mapped set → session ID,
    # so "user_attempts" displayed a row id, not a count. Aggregate
    # properly.
    counts = dict(
        db.query(ExamSession.exam_set_id, func.count(ExamSession.id))
          .filter(ExamSession.user_id == user.id,
                  ExamSession.exam_set_id.in_(set_ids))
          .group_by(ExamSession.exam_set_id).all()
    )
    # Sets where this user has a live draft → the frontend offers
    # Resume instead of Start. Liveness is budget-based (pause-on-leave
    # timer): remaining_seconds > 0; legacy rows (NULL budget, pre-0046)
    # fall back to the wall-clock rule.
    drafts = {
        row[0] for row in
        db.query(ExamSession.exam_set_id)
          .filter(ExamSession.user_id == user.id,
                  ExamSession.exam_set_id.in_(set_ids),
                  ExamSession.status == "in_progress",
                  or_(ExamSession.remaining_seconds > 0,
                      and_(ExamSession.remaining_seconds.is_(None),
                           ExamSession.expires_at > datetime.now(timezone.utc))))
          .all()
    }
    return [_to_summary(es, counts.get(es.id, 0), es.id in drafts,
                        question_count=qcounts.get(es.id, 0))
            for es in sets]


@router.get("/{slug}", response_model=ExamSetSummaryOut)
def get_set(slug: str, db: Session = Depends(get_db),
            user: User | None = Depends(get_optional_user)):
    es = db.query(ExamSet).filter_by(slug=slug, is_active=True).first()
    if not es:
        raise NotFoundError("Exam set not found.")
    n = 0
    draft = False
    if user:
        n = db.query(ExamSession).filter_by(
            user_id=user.id, exam_set_id=es.id,
        ).count()
        draft = db.query(ExamSession).filter(
            ExamSession.user_id == user.id,
            ExamSession.exam_set_id == es.id,
            ExamSession.status == "in_progress",
            or_(ExamSession.remaining_seconds > 0,
                and_(ExamSession.remaining_seconds.is_(None),
                     ExamSession.expires_at > datetime.now(timezone.utc))),
        ).first() is not None
    return _to_summary(es, n, draft,
                       question_count=_question_counts(db, [es.id]).get(es.id, 0))


@router.post("/{slug}/start", response_model=ExamAttemptOut, status_code=201)
def start_attempt(slug: str, db: Session = Depends(get_db),
                  actor=Depends(get_actor),
                  x_anon_token: str | None = Header(default=None,
                                                    alias="X-Anon-Token")):
    """Start (or resume) an attempt.

    Accepts either a signed-in user (Bearer token) or an anonymous browser-
    bound session (X-Anon-Token header — minted client-side). Premium sets
    reject anonymous callers up front; free sets are open to either. The
    anon token is also passed through for signed-in users so an orphaned
    anon draft from this browser can be adopted (see _adopt_orphan_draft).
    """
    return ExamService(db).start_attempt(actor, slug, anon_token=x_anon_token)


@router.post("/{slug}/practice/{domain_code}/start",
             response_model=ExamAttemptOut, status_code=201)
def start_domain_practice(slug: str, domain_code: str,
                          db: Session = Depends(get_db),
                          actor=Depends(get_actor),
                          x_anon_token: str | None = Header(default=None,
                                                            alias="X-Anon-Token")):
    """Start (or resume) a focused practice over one ECO domain's questions
    within a set. Reached from the results screen's per-domain drill-down.
    Same access rules as a full sitting (premium paywall still applies)."""
    return ExamService(db).start_domain_practice(actor, slug, domain_code,
                                                 anon_token=x_anon_token)
