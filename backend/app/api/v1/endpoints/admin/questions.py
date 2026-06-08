"""Admin question CRUD with strict validation + bulk Excel upload."""
from fastapi import APIRouter, Depends, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import select, func
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
from app.services.assistant.rag.ingest import reindex_quietly

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
                   exam_set_id: int | None = None,
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
    # Exact match — the admin UI sends a canonical ECO domain code ("D-I"),
    # and a substring match would let "D-I" leak "D-II"/"D-III" rows.
    if domain:   query = query.filter(Question.domain == domain)
    if exam_set_id:
        in_set = (db.query(ExamSetQuestion.question_id)
                  .filter(ExamSetQuestion.question_id == Question.id,
                          ExamSetQuestion.exam_set_id == exam_set_id)
                  .exists())
        query = query.filter(in_set)
    if q:        query = query.filter(Question.stem.ilike(f"%{q}%"))
    if tagged:
        link_exists = (db.query(ExamSetQuestion.question_id)
                       .filter(ExamSetQuestion.question_id == Question.id)
                       .exists())
        query = query.filter(link_exists if tagged == "any"
                              else ~link_exists)
    rows = query.order_by(Question.id.desc()).offset(offset).limit(limit).all()
    return _attach_in_sets(db, rows)


# IMPORTANT: declare static routes (`/bulk-template`, `/export`,
# `/bulk-upload`) BEFORE the dynamic `/{question_id}` route. FastAPI matches
# routes in declaration order; otherwise `bulk-template` is interpreted as a
# question_id and tries to coerce to int → 422.
@router.get("/bulk-template", include_in_schema=True)
def bulk_template(admin: User = Depends(get_admin_user)):
    """Return a BLANK .xlsx (headers + example rows + dropdowns). For most
    workflows admins want `/export` instead, which pre-fills live data."""
    blob = question_excel.build_template()
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="cpmai-questions-template.xlsx"',
        },
    )


@router.get("/export", include_in_schema=True)
def export_questions(db: Session = Depends(get_db),
                     admin: User = Depends(get_admin_user)):
    """Export EVERY question into the bulk sheet, pre-filled with the live
    data — id, all fields, ECO domain, and exam-set memberships. The admin
    edits this and re-uploads via `/bulk-upload`; rows keep their id so the
    upload updates in place (and syncs set memberships) rather than
    duplicating. One-shot bulk JOINs keep it O(1) in round-trips.
    """
    questions = (db.query(Question)
                 .order_by(Question.id.asc())
                 .all())
    topic_code_by_id = {t.id: t.code for t in db.query(Topic).all()}

    # question_id → [set slugs], ordered by display_order then id.
    slug_rows = db.execute(
        select(ExamSetQuestion.question_id, ExamSet.slug)
        .join(ExamSet, ExamSet.id == ExamSetQuestion.exam_set_id)
        .order_by(ExamSet.display_order, ExamSet.id)
    ).all()
    slugs_by_qid: dict[int, list[str]] = {}
    for qid, slug in slug_rows:
        slugs_by_qid.setdefault(qid, []).append(slug)

    rows = [
        question_excel.question_to_row(
            q, topic_code_by_id.get(q.topic_id, ""), slugs_by_qid.get(q.id, []))
        for q in questions
    ]
    blob = question_excel.build_export(rows)
    audit_log(db, admin.id, "question.bulk_export", {"count": len(rows)})
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="cpmai-questions.xlsx"',
        },
    )


def _sync_memberships(db: Session, q: Question, set_slugs: list[str],
                      sets_by_slug: dict[str, ExamSet], admin_id: int) -> None:
    """Make `q`'s exam-set memberships exactly match `set_slugs` (add the
    missing, drop the extras). New links append at the end of each set.
    Raises ValueError on an unknown slug so the row is reported, not
    silently dropped."""
    target_sets = []
    for slug in set_slugs:
        es = sets_by_slug.get(slug)
        if es is None:
            raise ValueError(f"unknown exam_set slug {slug!r}")
        target_sets.append(es)
    target_ids = {es.id for es in target_sets}

    existing = {link.exam_set_id: link for link in
                db.query(ExamSetQuestion).filter_by(question_id=q.id).all()}
    # Drop memberships no longer listed.
    for sid, link in existing.items():
        if sid not in target_ids:
            db.delete(link)
    # Add newly-listed memberships at the tail of each set.
    for es in target_sets:
        if es.id in existing:
            continue
        next_pos = (db.query(func.coalesce(func.max(ExamSetQuestion.position), -1))
                    .filter(ExamSetQuestion.exam_set_id == es.id).scalar() or 0)
        db.add(ExamSetQuestion(exam_set_id=es.id, question_id=q.id,
                               position=next_pos + 1, added_by=admin_id))


@router.post("/bulk-upload")
async def bulk_upload(file: UploadFile = File(...),
                      db: Session = Depends(get_db),
                      admin: User = Depends(get_admin_user)):
    """Parse an admin-supplied .xlsx and create OR update questions from it.

    Round-trip aware: a row with a blank `id` creates a new question; a row
    carrying an `id` updates that question in place (all fields + options),
    and — when the `exam_sets` column is present — syncs its set memberships
    to exactly the listed slugs. An absent `exam_sets` column leaves
    memberships untouched (back-compat with older sheets).

    Per-row partial success: valid rows commit, invalid rows come back in
    `errors` with a row number + reason. Each row is its own savepoint, so
    one bad row never poisons the rest. Validation reuses the SAME
    `_validate(payload)` the single-question POST uses — no path drift.
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

    # Resolve lookups once per upload (no N+1).
    topics_by_code = {t.code.upper(): t.id for t in db.query(Topic).all()}
    sets_by_slug = {s.slug: s for s in db.query(ExamSet).all()}

    created_ids: list[int] = []
    updated_ids: list[int] = []
    errors: list[dict] = list(parsed.errors)

    for pr in parsed.valid:
        topic_id = topics_by_code.get(pr.topic_code.upper())
        if topic_id is None:
            errors.append({"row": pr.row_num, "field": "topic_code",
                            "message": (f"unknown topic_code {pr.topic_code!r} — "
                                         f"valid: {sorted(topics_by_code.keys())}")})
            continue
        payload = pr.payload
        payload.topic_id = topic_id
        try:
            _validate(payload)
        except ValidationError as e:
            errors.append({"row": pr.row_num, "field": "validation",
                            "message": e.detail if isinstance(e.detail, str)
                                       else e.detail.get("message", str(e.detail))})
            continue

        # Each row is its own savepoint — a single DB-level failure (e.g. an
        # unexpected integrity error) doesn't roll back the whole upload.
        # Remember the success-list lengths so a mid-row failure can undo
        # any id we optimistically appended before the savepoint rolled back.
        pre_created, pre_updated = len(created_ids), len(updated_ids)
        sp = db.begin_nested()
        try:
            if pr.question_id is not None:
                q = db.get(Question, pr.question_id)
                if q is None:
                    raise ValueError(f"id {pr.question_id} not found — "
                                     f"leave id blank to create a new question")
                # Update scalar fields, then replace options wholesale
                # (clear + flush before re-insert to dodge the unique
                # (question_id, option_letter) constraint mid-flush).
                for f in ("stem", "topic_id", "domain", "task", "enablers",
                          "remarks", "difficulty", "question_type",
                          "explanation", "is_active"):
                    setattr(q, f, getattr(payload, f))
                q.options.clear()
                db.flush()
                q.options = [QuestionOption(**o.model_dump()) for o in payload.options]
                db.flush()
                updated_ids.append(q.id)
            else:
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

            # Sync set memberships only when the column was present.
            if pr.set_slugs is not None:
                _sync_memberships(db, q, pr.set_slugs, sets_by_slug, admin.id)
            sp.commit()
        except ValueError as e:
            sp.rollback()
            del created_ids[pre_created:]; del updated_ids[pre_updated:]
            errors.append({"row": pr.row_num, "field": "exam_sets"
                            if "slug" in str(e) else "row",
                            "message": str(e)})
        except Exception as e:
            sp.rollback()
            del created_ids[pre_created:]; del updated_ids[pre_updated:]
            errors.append({"row": pr.row_num, "field": "db",
                            "message": f"write failed: {type(e).__name__}: {e}"})

    db.commit()
    # Keep the RAG corpus in sync for every question we touched.
    for qid in created_ids + updated_ids:
        reindex_quietly(db, "question_explanation", qid)
    audit_log(db, admin.id, "question.bulk_upload",
              {"created": len(created_ids), "updated": len(updated_ids),
               "errors": len(errors), "filename": file.filename})

    return {
        "created": len(created_ids),
        "created_ids": created_ids,
        "updated": len(updated_ids),
        "updated_ids": updated_ids,
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
    # Keep RAG corpus in sync if the question carries an explanation.
    reindex_quietly(db, "question_explanation", q.id)
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
    reindex_quietly(db, "question_explanation", q.id)
    return _attach_in_sets(db, [q])[0]


@router.delete("/{question_id}", status_code=204)
def delete_question(question_id: int, db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    q = db.get(Question, question_id)
    if not q: raise NotFoundError()
    db.delete(q); db.commit()
    audit_log(db, admin.id, "question.deleted", {"id": question_id})
    reindex_quietly(db, "question_explanation", question_id)
