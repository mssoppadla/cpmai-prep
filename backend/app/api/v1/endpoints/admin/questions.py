"""Admin question CRUD with strict validation + bulk Excel upload."""
from fastapi import APIRouter, Depends, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_admin_user
from app.core.exceptions import NotFoundError, ValidationError
from app.core.audit import audit_log
from app.models.user import User
from app.models.question import Question, QuestionOption, QuestionType
from app.models.exam_set import ExamSet, ExamSetQuestion
from app.models.topic import Topic
from app.schemas.question import QuestionAdminIn, QuestionAdminOut
from app.services import question_excel

router = APIRouter()

# 5 MB file-size cap — protects the request lifecycle from accidental
# huge uploads. Per-row cap (500) is enforced inside the parser.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _validate(payload: QuestionAdminIn):
    if not 2 <= len(payload.options) <= 6:
        raise ValidationError("Question must have 2-6 options")
    letters = [o.option_letter for o in payload.options]
    if len(set(letters)) != len(letters):
        raise ValidationError("Option letters must be unique within a question.")
    correct_count = sum(1 for o in payload.options if o.is_correct)
    if payload.question_type == QuestionType.SINGLE_CHOICE:
        if correct_count != 1:
            raise ValidationError(
                "Single-choice questions must have exactly one correct option.")
    else:  # MULTI_CHOICE
        if correct_count < 2:
            raise ValidationError(
                "Multi-choice questions must have at least 2 correct options. "
                "If only one is correct, set the question type to single_choice.")
        if correct_count == len(payload.options):
            raise ValidationError(
                "Multi-choice questions must have at least one INCORRECT "
                "option (otherwise the question is unanswerable wrong).")


def _attach_in_sets(db: Session, questions: list[Question]) -> list[QuestionAdminOut]:
    """Hydrate `in_sets` on each question without N+1 queries.

    One bulk SELECT pulls every (question_id, set_id, slug, name) link
    for the questions in the response, then we group them in Python.
    O(1) DB roundtrips regardless of result-set size.

    Returns a list of QuestionAdminOut in the SAME order as `questions`.
    """
    if not questions:
        return []
    qids = [q.id for q in questions]
    rows = db.execute(
        select(ExamSetQuestion.question_id,
                ExamSet.id, ExamSet.slug, ExamSet.name)
        .join(ExamSet, ExamSet.id == ExamSetQuestion.exam_set_id)
        .where(ExamSetQuestion.question_id.in_(qids))
        .order_by(ExamSet.display_order, ExamSet.id)
    ).all()
    grouped: dict[int, list[dict]] = {qid: [] for qid in qids}
    for qid, sid, slug, name in rows:
        grouped[qid].append({"id": sid, "slug": slug, "name": name})
    return [
        QuestionAdminOut.model_validate(
            {**QuestionAdminOut.model_validate(q).model_dump(),
              "in_sets": grouped.get(q.id, [])}
        )
        for q in questions
    ]


@router.get("", response_model=list[QuestionAdminOut])
def list_questions(db: Session = Depends(get_db),
                   topic_id: int | None = None,
                   domain: str | None = None,
                   q: str | None = None,
                   tagged: str | None = Query(
                       None,
                       pattern="^(any|none)$",
                       description="Filter by tag-state: 'any' = in ≥1 set, "
                                    "'none' = in zero sets, omit = no filter.",
                   ),
                   limit: int = Query(50, le=1000),
                   offset: int = 0):
    """List questions with optional filters.

    `tagged` is the picker-helper added with the cross-set visibility
    feature: an admin browsing the bank wants to find orphans
    ("untagged" — never linked to any set) or to deliberately surface
    questions already living elsewhere. Implemented via a correlated
    EXISTS subquery so it composes cleanly with topic/domain/search
    filters and doesn't pull data through Python.
    """
    query = db.query(Question)
    if topic_id: query = query.filter(Question.topic_id == topic_id)
    if domain:   query = query.filter(Question.domain.ilike(f"%{domain}%"))
    if q:        query = query.filter(Question.stem.ilike(f"%{q}%"))
    if tagged:
        link_exists = (db.query(ExamSetQuestion.question_id)
                       .filter(ExamSetQuestion.question_id == Question.id)
                       .exists())
        query = query.filter(link_exists if tagged == "any"
                              else ~link_exists)
    rows = query.order_by(Question.id.desc()).offset(offset).limit(limit).all()
    return _attach_in_sets(db, rows)


# IMPORTANT: declare static routes (`/bulk-template`, `/bulk-upload`)
# BEFORE the dynamic `/{question_id}` route. FastAPI matches routes in
# declaration order; otherwise `bulk-template` is interpreted as a
# question_id and tries to coerce to int → 422.
@router.get("/bulk-template", include_in_schema=True)
def bulk_template(admin: User = Depends(get_admin_user)):
    """Return an .xlsx admins fill in to upload many questions at once.

    Includes pre-filled example rows + data-validation dropdowns for
    enum-shaped columns (difficulty, question_type, topic_code, every
    *_is_correct) so admins can't typo those values.
    """
    blob = question_excel.build_template()
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="cpmai-questions-template.xlsx"',
        },
    )


@router.post("/bulk-upload")
async def bulk_upload(file: UploadFile = File(...),
                      db: Session = Depends(get_db),
                      admin: User = Depends(get_admin_user)):
    """Parse an admin-supplied .xlsx and create questions from it.

    Per-row partial success: valid rows commit, invalid rows come back
    in the `errors` array with row number + reason so the admin can
    fix the failing rows in their sheet and re-upload only those.

    Validates each row through the SAME `_validate(payload)` function
    `POST /admin/questions` uses — bulk path can't drift from single.
    Wraps every row in a savepoint so one bad insert doesn't poison
    the rest.
    """
    # File size guard — read in one shot since we capped at 5MB.
    blob = await file.read()
    if len(blob) > MAX_UPLOAD_BYTES:
        raise ValidationError(
            f"File too large ({len(blob)} bytes). Max {MAX_UPLOAD_BYTES} bytes "
            f"(~{MAX_UPLOAD_BYTES // (1024*1024)} MB) per upload.")
    if len(blob) == 0:
        raise ValidationError("Uploaded file is empty.")

    parsed = question_excel.parse_workbook(blob)

    # Resolve topic_code → topic_id once per upload (single query, no N+1).
    topics_by_code = {t.code.upper(): t.id
                      for t in db.query(Topic).all()}

    created_ids: list[int] = []
    errors: list[dict] = list(parsed.errors)

    for row_num, payload, topic_code in parsed.valid:
        topic_id = topics_by_code.get(topic_code.upper())
        if topic_id is None:
            errors.append({"row": row_num, "field": "topic_code",
                            "message": (f"unknown topic_code {topic_code!r} — "
                                         f"valid: {sorted(topics_by_code.keys())}")})
            continue
        # Bind the resolved topic and run the EXACT SAME validator
        # /admin/questions POST uses — no drift between paths.
        payload.topic_id = topic_id
        try:
            _validate(payload)
        except ValidationError as e:
            errors.append({"row": row_num, "field": "validation",
                            "message": e.detail if isinstance(e.detail, str)
                                       else e.detail.get("message", str(e.detail))})
            continue

        # Wrap each insert in a savepoint so a single DB-level failure
        # (e.g. an integrity constraint we didn't anticipate) doesn't
        # roll back the entire upload.
        sp = db.begin_nested()
        try:
            q = Question(
                stem=payload.stem, topic_id=payload.topic_id,
                domain=payload.domain, task=payload.task,
                enablers=payload.enablers, remarks=payload.remarks,
                difficulty=payload.difficulty,
                question_type=payload.question_type,
                explanation=payload.explanation,
                is_active=payload.is_active, created_by=admin.id,
            )
            q.options = [QuestionOption(**o.model_dump()) for o in payload.options]
            db.add(q)
            db.flush()
            created_ids.append(q.id)
            sp.commit()
        except Exception as e:
            sp.rollback()
            errors.append({"row": row_num, "field": "db",
                            "message": f"insert failed: {type(e).__name__}: {e}"})

    db.commit()
    audit_log(db, admin.id, "question.bulk_upload",
              {"created": len(created_ids), "errors": len(errors),
               "filename": file.filename})

    return {
        "created": len(created_ids),
        "created_ids": created_ids,
        "errors": errors,
    }


@router.get("/{question_id}", response_model=QuestionAdminOut)
def get_question(question_id: int, db: Session = Depends(get_db)):
    q = db.get(Question, question_id)
    if not q: raise NotFoundError()
    return _attach_in_sets(db, [q])[0]


@router.post("", response_model=QuestionAdminOut, status_code=201)
def create_question(payload: QuestionAdminIn,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    _validate(payload)
    q = Question(
        stem=payload.stem, topic_id=payload.topic_id,
        domain=payload.domain, task=payload.task,
        enablers=payload.enablers, remarks=payload.remarks,
        difficulty=payload.difficulty,
        question_type=payload.question_type,
        explanation=payload.explanation,
        is_active=payload.is_active, created_by=admin.id,
    )
    q.options = [QuestionOption(**o.model_dump()) for o in payload.options]
    db.add(q); db.commit(); db.refresh(q)
    audit_log(db, admin.id, "question.created", {"id": q.id})
    # New question is unattached — in_sets defaults to [].
    return _attach_in_sets(db, [q])[0]


@router.patch("/{question_id}", response_model=QuestionAdminOut)
def update_question(question_id: int, payload: QuestionAdminIn,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    q = db.get(Question, question_id)
    if not q: raise NotFoundError()
    _validate(payload)
    for f in ("stem", "topic_id", "domain", "task", "enablers",
              "remarks", "difficulty", "question_type",
              "explanation", "is_active"):
        setattr(q, f, getattr(payload, f))
    # Replace options: clear old rows and flush before inserting new ones,
    # otherwise the unique (question_id, option_letter) constraint trips
    # because the INSERT can race ahead of the DELETE in the same flush.
    q.options.clear()
    db.flush()
    q.options = [QuestionOption(**o.model_dump()) for o in payload.options]
    db.commit(); db.refresh(q)
    audit_log(db, admin.id, "question.updated", {"id": q.id})
    return _attach_in_sets(db, [q])[0]


@router.delete("/{question_id}", status_code=204)
def delete_question(question_id: int, db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    q = db.get(Question, question_id)
    if not q: raise NotFoundError()
    db.delete(q); db.commit()
    audit_log(db, admin.id, "question.deleted", {"id": question_id})
