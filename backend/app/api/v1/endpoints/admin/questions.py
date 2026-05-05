"""Admin question CRUD with strict validation."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_admin_user
from app.core.exceptions import NotFoundError, ValidationError
from app.core.audit import audit_log
from app.models.user import User
from app.models.question import Question, QuestionOption
from app.schemas.question import QuestionAdminIn, QuestionAdminOut

router = APIRouter()


def _validate(payload: QuestionAdminIn):
    if not 2 <= len(payload.options) <= 6:
        raise ValidationError("Question must have 2-6 options")
    correct = [o for o in payload.options if o.is_correct]
    if len(correct) != 1:
        raise ValidationError("Exactly one option must be marked correct.")
    letters = [o.option_letter for o in payload.options]
    if len(set(letters)) != len(letters):
        raise ValidationError("Option letters must be unique within a question.")


@router.get("", response_model=list[QuestionAdminOut])
def list_questions(db: Session = Depends(get_db),
                   topic_id: int | None = None,
                   domain: str | None = None,
                   q: str | None = None,
                   limit: int = Query(50, le=1000),
                   offset: int = 0):
    query = db.query(Question)
    if topic_id: query = query.filter(Question.topic_id == topic_id)
    if domain:   query = query.filter(Question.domain.ilike(f"%{domain}%"))
    if q:        query = query.filter(Question.stem.ilike(f"%{q}%"))
    return query.order_by(Question.id.desc()).offset(offset).limit(limit).all()


@router.get("/{question_id}", response_model=QuestionAdminOut)
def get_question(question_id: int, db: Session = Depends(get_db)):
    q = db.get(Question, question_id)
    if not q: raise NotFoundError()
    return q


@router.post("", response_model=QuestionAdminOut, status_code=201)
def create_question(payload: QuestionAdminIn,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    _validate(payload)
    q = Question(
        stem=payload.stem, topic_id=payload.topic_id,
        domain=payload.domain, task=payload.task,
        enablers=payload.enablers, remarks=payload.remarks,
        difficulty=payload.difficulty, explanation=payload.explanation,
        is_active=payload.is_active, created_by=admin.id,
    )
    q.options = [QuestionOption(**o.model_dump()) for o in payload.options]
    db.add(q); db.commit(); db.refresh(q)
    audit_log(db, admin.id, "question.created", {"id": q.id})
    return q


@router.patch("/{question_id}", response_model=QuestionAdminOut)
def update_question(question_id: int, payload: QuestionAdminIn,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    q = db.get(Question, question_id)
    if not q: raise NotFoundError()
    _validate(payload)
    for f in ("stem", "topic_id", "domain", "task", "enablers",
              "remarks", "difficulty", "explanation", "is_active"):
        setattr(q, f, getattr(payload, f))
    q.options = [QuestionOption(**o.model_dump()) for o in payload.options]
    db.commit(); db.refresh(q)
    audit_log(db, admin.id, "question.updated", {"id": q.id})
    return q


@router.delete("/{question_id}", status_code=204)
def delete_question(question_id: int, db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    q = db.get(Question, question_id)
    if not q: raise NotFoundError()
    db.delete(q); db.commit()
    audit_log(db, admin.id, "question.deleted", {"id": question_id})
