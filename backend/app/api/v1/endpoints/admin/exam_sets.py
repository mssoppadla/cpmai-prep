"""Admin exam set CRUD + question linkage."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_admin_user, get_super_admin_user
from app.core.exceptions import NotFoundError, ConflictError
from app.core.audit import audit_log
from app.core.settings_store import settings_store
from app.models.exam_set import ExamSet, ExamSetQuestion
from app.models.user import User
from app.schemas.exam_set import (
    ExamSetSummaryOut, ExamSetAdminIn, AddQuestionsIn, ReorderIn,
    ExamSetLinkedQuestion,
)
from app.models.question import Question
from app.schemas.question import QuestionAdminOut

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
def list_sets(db: Session = Depends(get_db),
              limit: int = Query(50, le=200), offset: int = 0):
    sets = (db.query(ExamSet)
            .order_by(ExamSet.display_order, ExamSet.id)
            .offset(offset).limit(limit).all())
    return [_to_summary(es) for es in sets]


@router.post("", response_model=ExamSetSummaryOut, status_code=201)
def create_set(payload: ExamSetAdminIn,
               db: Session = Depends(get_db),
               admin: User = Depends(get_admin_user)):
    if db.query(ExamSet).filter_by(slug=payload.slug).first():
        raise ConflictError(f"Slug '{payload.slug}' already in use.")
    if db.query(ExamSet).filter_by(name=payload.name).first():
        raise ConflictError(f"Name '{payload.name}' already in use.")
    es = ExamSet(**payload.model_dump(), created_by=admin.id)
    db.add(es); db.commit(); db.refresh(es)
    audit_log(db, admin.id, "exam_set.created",
              {"id": es.id, "slug": es.slug})
    return _to_summary(es)


@router.patch("/{set_id}", response_model=ExamSetSummaryOut)
def update_set(set_id: int, payload: ExamSetAdminIn,
               db: Session = Depends(get_db),
               admin: User = Depends(get_admin_user)):
    es = db.get(ExamSet, set_id)
    if not es: raise NotFoundError()
    for f, v in payload.model_dump(exclude_unset=True).items():
        setattr(es, f, v)
    db.commit(); db.refresh(es)
    audit_log(db, admin.id, "exam_set.updated", {"id": es.id})
    return _to_summary(es)



@router.get("/{set_id}/questions", response_model=list[ExamSetLinkedQuestion])
def list_linked_questions(set_id: int,
                          db: Session = Depends(get_db),
                          admin: User = Depends(get_admin_user)):
    """Return questions in this set ordered by position, with full admin data."""
    es = db.get(ExamSet, set_id)
    if not es: raise NotFoundError()
    links = (db.query(ExamSetQuestion)
             .filter_by(exam_set_id=set_id)
             .order_by(ExamSetQuestion.position).all())
    out: list[ExamSetLinkedQuestion] = []
    for link in links:
        q = db.get(Question, link.question_id)
        if q is None:
            continue
        out.append(ExamSetLinkedQuestion(
            position=link.position,
            question=QuestionAdminOut.model_validate(q),
        ))
    return out


@router.post("/{set_id}/questions", status_code=204)
def add_questions(set_id: int, payload: AddQuestionsIn,
                  db: Session = Depends(get_db),
                  admin: User = Depends(get_admin_user)):
    es = db.get(ExamSet, set_id)
    if not es: raise NotFoundError()
    existing = {q.id for q in es.questions}
    last = (db.query(ExamSetQuestion).filter_by(exam_set_id=set_id)
            .order_by(ExamSetQuestion.position.desc()).first())
    pos_val = last.position if last else 0
    added = 0
    for qid in payload.question_ids:
        if qid in existing: continue
        pos_val += 10
        db.add(ExamSetQuestion(exam_set_id=set_id, question_id=qid,
                                position=pos_val, added_by=admin.id))
        added += 1
    db.commit()
    audit_log(db, admin.id, "exam_set.questions_added",
              {"set_id": set_id, "added": added})


@router.delete("/{set_id}/questions/{question_id}", status_code=204)
def remove_question(set_id: int, question_id: int,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    deleted = (db.query(ExamSetQuestion)
               .filter_by(exam_set_id=set_id, question_id=question_id)
               .delete())
    db.commit()
    if not deleted: raise NotFoundError()
    audit_log(db, admin.id, "exam_set.question_removed",
              {"set_id": set_id, "question_id": question_id})


@router.patch("/{set_id}/questions/reorder", status_code=204)
def reorder_questions(set_id: int, payload: ReorderIn,
                      db: Session = Depends(get_db),
                      admin: User = Depends(get_admin_user)):
    rows = {r.question_id: r for r in
            db.query(ExamSetQuestion).filter_by(exam_set_id=set_id).all()}
    for item in payload.items:
        qid = item.get("question_id"); pos = item.get("position")
        if qid in rows and isinstance(pos, int):
            rows[qid].position = pos
    db.commit()
    audit_log(db, admin.id, "exam_set.questions_reordered",
              {"set_id": set_id, "count": len(payload.items)})


@router.delete("/{set_id}", status_code=204)
def delete_set(set_id: int, db: Session = Depends(get_db),
               admin: User = Depends(get_super_admin_user)):
    es = db.get(ExamSet, set_id)
    if not es: raise NotFoundError()
    db.delete(es); db.commit()
    audit_log(db, admin.id, "exam_set.deleted", {"id": set_id})
