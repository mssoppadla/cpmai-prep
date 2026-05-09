"""Exam attempt lifecycle: start, save answer, submit, score, result.

Critical correctness: answers + reasoning are NEVER returned during attempt.
Only the SubmitAttemptOut payload reveals them.

Two actor types are supported:
  - User       → signed-in attempt; session.user_id is set
  - str (anon) → anonymous browser-bound attempt via X-Anon-Token; the
                 service stores the token on session.anon_token. Premium
                 sets reject anon callers up front.
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.core.exceptions import (
    NotFoundError, ConflictError, ForbiddenError, SubscriptionRequiredError,
    UnauthorizedError,
)
from app.core.audit import audit_log
from app.services.tracking_service import emit_event
from app.models.user import User
from app.models.exam_set import ExamSet, ExamSetQuestion
from app.models.exam_session import ExamSession, ExamAttemptAnswer
from app.models.question import Question, QuestionOption, QuestionType
from app.models.topic import Topic
from app.models.subscription import Subscription
from app.models.plan import PlanExamSet
from app.schemas.exam import (
    ExamAttemptOut, AnswerIn, SubmitAttemptOut, PhaseBreakdown,
)
from app.schemas.exam_set import ExamSetSummaryOut
from app.schemas.question import (
    QuestionAttemptView, QuestionOptionOut,
    QuestionResultView, QuestionOptionResultOut,
)


# ----------------------------------------------------- selection helpers
# These small helpers unify single_choice and multi_choice handling so
# the scoring loops below stay readable. Both paths converge on a `set`
# of option letters — `selected == correct_set` becomes the one rule.

def _user_selected_set(ans, question) -> set[str]:
    """The set of option letters the user picked. Empty = unanswered."""
    if question.question_type == QuestionType.MULTI_CHOICE:
        return set(ans.selected_letters or [])
    if ans.selected_letter:
        return {ans.selected_letter}
    return set()


def _correct_set(question) -> set[str]:
    """The set of option letters the question's author marked is_correct."""
    return {o.option_letter for o in question.options if o.is_correct}


class ExamService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ start
    def start_attempt(self, actor: "User | str | None",
                      exam_set_slug: str) -> ExamAttemptOut:
        if actor is None:
            raise UnauthorizedError(
                "Provide an Authorization header or X-Anon-Token to start.",
            )
        es = self.db.query(ExamSet).filter_by(slug=exam_set_slug, is_active=True).first()
        if not es:
            raise NotFoundError("Exam set not found")
        if es.is_premium:
            if not isinstance(actor, User):
                raise UnauthorizedError(
                    "Premium sets require a signed-in account. Sign in to "
                    "subscribe and unlock.",
                )
            if not self._can_access_exam_set(actor.id, es.id):
                raise SubscriptionRequiredError()
        if not es.questions:
            raise ConflictError("Exam set has no questions yet.")

        # Block multiple in-progress sessions for the same set, scoped to the
        # caller (a logged-in user gets one session per set; an anon token
        # gets one session per set per browser).
        if isinstance(actor, User):
            existing_q = self.db.query(ExamSession).filter_by(
                user_id=actor.id, exam_set_id=es.id, status="in_progress",
            )
        else:
            existing_q = self.db.query(ExamSession).filter_by(
                anon_token=actor, exam_set_id=es.id, status="in_progress",
            )
        existing = existing_q.first()
        if existing and existing.expires_at > datetime.now(timezone.utc):
            # Backfill answer rows for any questions added to the set
            # AFTER this session started, so they're answerable now.
            self._ensure_answer_rows(existing, es)
            return self._serialize_attempt(existing, es)

        now = datetime.now(timezone.utc)
        session = ExamSession(
            user_id=actor.id if isinstance(actor, User) else None,
            anon_token=None if isinstance(actor, User) else actor,
            exam_set_id=es.id,
            started_at=now,
            expires_at=now + timedelta(minutes=es.time_limit_minutes),
            status="in_progress",
        )
        self.db.add(session)
        self.db.flush()
        # Create empty answer rows (one per question) for fast updates.
        for q in es.questions:
            self.db.add(ExamAttemptAnswer(
                exam_session_id=session.id, question_id=q.id,
            ))
        self.db.commit()
        self.db.refresh(session)
        actor_user_id = actor.id if isinstance(actor, User) else None
        audit_log(self.db, actor_user_id, "exam.attempt_started",
                  {"exam_set_id": es.id, "session_id": session.id,
                   "anonymous": actor_user_id is None})
        emit_event(self.db, "exam.started", user_id=actor_user_id,
                   metadata={"exam_set_id": es.id, "exam_set_slug": es.slug,
                             "exam_session_id": session.id,
                             "is_premium": es.is_premium,
                             "anonymous": actor_user_id is None})
        return self._serialize_attempt(session, es)

    # ------------------------------------------------------------------- get
    def get_attempt(self, actor: "User | str | None",
                    attempt_id: int) -> ExamAttemptOut:
        session = self._load_session(actor, attempt_id)
        # Auto-expire if time is up
        if session.status == "in_progress" and session.expires_at < datetime.now(timezone.utc):
            session.status = "expired"
            self.db.commit()
        es = self.db.get(ExamSet, session.exam_set_id)
        return self._serialize_attempt(session, es)

    # ---------------------------------------------------------------- answer
    def save_answer(self, actor: "User | str | None",
                    attempt_id: int, payload: AnswerIn):
        session = self._load_session(actor, attempt_id)
        if session.status != "in_progress":
            raise ConflictError(f"Cannot modify a {session.status} attempt.")
        if session.expires_at < datetime.now(timezone.utc):
            session.status = "expired"
            self.db.commit()
            raise ConflictError("Time is up.")

        ans = self.db.query(ExamAttemptAnswer).filter_by(
            exam_session_id=session.id, question_id=payload.question_id,
        ).first()
        if not ans:
            # Defensive: a question may have been linked to the set
            # AFTER this session started. Verify it's currently in the
            # set, then create the missing answer row on the fly.
            in_set = self.db.query(ExamSetQuestion).filter_by(
                exam_set_id=session.exam_set_id,
                question_id=payload.question_id,
            ).first()
            if not in_set:
                raise NotFoundError("Question not part of this attempt.")
            ans = ExamAttemptAnswer(
                exam_session_id=session.id,
                question_id=payload.question_id,
            )
            self.db.add(ans)
            self.db.flush()
        # Persist into the column matching the question's type. Mismatch
        # between payload shape and question type is a 400 — better to
        # surface a programmer error than silently coerce.
        question = self.db.get(Question, payload.question_id)
        if question is None:
            raise NotFoundError("Question not found.")
        if question.question_type == QuestionType.MULTI_CHOICE:
            if payload.selected_letter is not None:
                raise ConflictError(
                    "This is a multi-choice question; send `selected_letters` "
                    "(a list), not `selected_letter`.")
            # Normalize: dedupe + sort so storage is canonical.
            letters = (sorted(set(payload.selected_letters))
                       if payload.selected_letters else None)
            ans.selected_letter = None
            ans.selected_letters = letters
        else:  # SINGLE_CHOICE
            if payload.selected_letters is not None:
                raise ConflictError(
                    "This is a single-choice question; send `selected_letter` "
                    "(a string), not `selected_letters`.")
            ans.selected_letter = payload.selected_letter
            ans.selected_letters = None
        ans.marked_for_review = payload.marked_for_review
        ans.answered_at = datetime.now(timezone.utc)
        self.db.commit()

    # ---------------------------------------------------------------- submit
    def submit(self, actor: "User | str | None",
               attempt_id: int) -> SubmitAttemptOut:
        session = self._load_session(actor, attempt_id)
        if session.status != "in_progress":
            raise ConflictError(f"Already {session.status}.")

        now = datetime.now(timezone.utc)
        es = self.db.get(ExamSet, session.exam_set_id)
        questions = es.questions
        question_map = {q.id: q for q in questions}

        correct = 0; incorrect = 0; unanswered = 0
        results: list[QuestionResultView] = []
        phase_counts: dict[int, dict] = {}

        for ans in session.answers:
            q = question_map.get(ans.question_id)
            if not q:
                continue
            selected = _user_selected_set(ans, q)
            correct_set = _correct_set(q)
            is_correct = bool(selected) and selected == correct_set
            ans.is_correct = is_correct

            if not selected:
                unanswered += 1
            elif is_correct:
                correct += 1
            else:
                incorrect += 1

            # Per-phase tally
            slot = phase_counts.setdefault(q.topic_id, {"correct": 0, "total": 0})
            slot["total"] += 1
            if is_correct:
                slot["correct"] += 1

            # Build result view (full reveal)
            results.append(QuestionResultView(
                id=q.id, stem=q.stem, topic_id=q.topic_id,
                domain=q.domain, task=q.task,
                enablers=q.enablers or [], remarks=q.remarks,
                difficulty=q.difficulty,
                question_type=q.question_type,
                explanation=q.explanation,
                is_user_correct=is_correct,
                options=[
                    QuestionOptionResultOut(
                        option_letter=o.option_letter, text=o.text,
                        is_correct=o.is_correct, reasoning=o.reasoning,
                        selected_by_user=(o.option_letter in selected),
                    )
                    for o in q.options
                ],
            ))

        total = correct + incorrect + unanswered
        score = round((correct / total) * 100) if total else 0
        passed = score >= (es.passing_score if es else 70)

        session.status = "submitted"
        session.submitted_at = now
        session.score = score
        session.passed = passed
        session.time_taken_seconds = int((now - session.started_at).total_seconds())
        self.db.commit()

        # Phase breakdown with topic codes
        topics = {t.id: t for t in self.db.query(Topic).all()}
        by_phase = [
            PhaseBreakdown(
                topic_code=topics[tid].code if tid in topics else "?",
                topic_name=topics[tid].name if tid in topics else "Unknown",
                correct=v["correct"], total=v["total"],
                percent=round((v["correct"] / v["total"]) * 100) if v["total"] else 0,
            )
            for tid, v in phase_counts.items()
        ]
        by_phase.sort(key=lambda p: topics[next(
            tid for tid in topics if topics[tid].code == p.topic_code
        )].order if p.topic_code in {t.code for t in topics.values()} else 99)

        actor_user_id = session.user_id  # None for anon
        audit_log(self.db, actor_user_id, "exam.attempt_submitted",
                  {"session_id": session.id, "score": score, "passed": passed,
                   "anonymous": actor_user_id is None})
        emit_event(self.db, "exam.submitted", user_id=actor_user_id,
                   metadata={"exam_set_id": es.id if es else None,
                             "exam_session_id": session.id,
                             "score": score, "passed": passed,
                             "correct": correct, "incorrect": incorrect,
                             "unanswered": unanswered,
                             "anonymous": actor_user_id is None})

        return SubmitAttemptOut(
            id=session.id, score=score, passed=passed,
            correct_count=correct, incorrect_count=incorrect,
            unanswered_count=unanswered,
            time_taken_seconds=session.time_taken_seconds,
            questions=results, by_phase=by_phase,
        )

    # -------------------------------------------------------------- helpers
    def _ensure_answer_rows(self, session: "ExamSession", es: "ExamSet") -> None:
        """Make sure there's a one-to-one mapping between current set
        questions and answer rows. Creates rows for any question that
        was added to the set after this session began."""
        existing = {a.question_id for a in self.db.query(ExamAttemptAnswer)
                    .filter_by(exam_session_id=session.id).all()}
        added = 0
        for q in es.questions:
            if q.id in existing:
                continue
            self.db.add(ExamAttemptAnswer(
                exam_session_id=session.id, question_id=q.id,
            ))
            added += 1
        if added:
            self.db.commit()

    def _load_session(self, actor: "User | str | None",
                      attempt_id: int) -> ExamSession:
        session = self.db.get(ExamSession, attempt_id)
        if not session:
            raise NotFoundError("Attempt not found.")
        if isinstance(actor, User):
            if session.user_id != actor.id:
                raise ForbiddenError()
        elif isinstance(actor, str):
            # Anon: must match the stored anon_token. Refuse if the session
            # was created by a logged-in user (don't let a guest hijack via
            # an attempt_id guess).
            if session.user_id is not None or session.anon_token != actor:
                raise ForbiddenError()
        else:
            raise UnauthorizedError("Sign in or provide X-Anon-Token.")
        return session

    def _has_active_subscription(self, user_id: int) -> bool:
        """Legacy any-active-sub check. Preserved for non-paywall code paths."""
        return bool(self.db.query(Subscription).filter_by(
            user_id=user_id, status="active",
        ).first())

    def _can_access_exam_set(self, user_id: int, exam_set_id: int) -> bool:
        """Paywall check: does the user have access to this premium set?

        Two paths grant access:
          1. Any active subscription with `plan_id IS NULL` (legacy
             pre-plan rows — kept for backward compatibility).
          2. An active, non-expired subscription whose Plan includes
             this exam_set_id via plan_exam_sets.

        `expires_at IS NULL` is treated as "no expiry" (legacy).
        """
        from sqlalchemy import or_
        now = datetime.now(timezone.utc)
        not_expired = or_(Subscription.expires_at.is_(None),
                          Subscription.expires_at > now)
        subs = (self.db.query(Subscription)
                .filter(Subscription.user_id == user_id,
                        Subscription.status == "active",
                        not_expired)
                .all())
        if not subs:
            return False
        # Legacy: any sub without a plan_id grants blanket access (mirrors
        # the historic _has_active_subscription behaviour for rows that
        # predate the plans system).
        if any(s.plan_id is None for s in subs):
            return True
        # Plan-based: at least one active sub points to a Plan that
        # includes this exam set.
        plan_ids = [s.plan_id for s in subs if s.plan_id is not None]
        link = (self.db.query(PlanExamSet)
                .filter(PlanExamSet.plan_id.in_(plan_ids),
                        PlanExamSet.exam_set_id == exam_set_id)
                .first())
        return link is not None

    def _serialize_attempt(self, session: ExamSession, es: ExamSet) -> ExamAttemptOut:
        # Per-question current selection. Single-choice → letter | None.
        # Multi-choice → comma-joined sorted letters | None (so the wire
        # type stays `dict[int, str | None]` and the frontend just splits
        # on ',' for multi questions). Empty selection → None either way.
        question_by_id = {q.id: q for q in es.questions}
        user_answers: dict[int, str | None] = {}
        for a in session.answers:
            q = question_by_id.get(a.question_id)
            if q is None:
                user_answers[a.question_id] = None
                continue
            if q.question_type == QuestionType.MULTI_CHOICE:
                letters = a.selected_letters or []
                user_answers[a.question_id] = (",".join(sorted(letters))
                                                if letters else None)
            else:
                user_answers[a.question_id] = a.selected_letter

        # Strip correct/reasoning from options before sending
        questions: list[QuestionAttemptView] = []
        for q in es.questions:
            questions.append(QuestionAttemptView(
                id=q.id, stem=q.stem, topic_id=q.topic_id,
                domain=q.domain, task=q.task, difficulty=q.difficulty,
                question_type=q.question_type,
                options=[QuestionOptionOut(option_letter=o.option_letter, text=o.text)
                         for o in q.options],
            ))

        return ExamAttemptOut(
            id=session.id,
            exam_set=ExamSetSummaryOut(
                id=es.id, name=es.name, slug=es.slug, description=es.description,
                difficulty=es.difficulty, time_limit_minutes=es.time_limit_minutes,
                passing_score=es.passing_score, is_premium=es.is_premium,
                cover_image_url=es.cover_image_url,
                question_count=len(es.questions),
            ),
            started_at=session.started_at, expires_at=session.expires_at,
            status=session.status, questions=questions,
            user_answers=user_answers,
        )

    # ---------------------------------------------------------------- result
    def get_result(self, actor: "User | str | None",
                   attempt_id: int) -> SubmitAttemptOut:
        """Cold-load a submitted attempt's result. Reconstructs reasoning view."""
        session = self._load_session(actor, attempt_id)
        if session.status != "submitted":
            raise ConflictError(f"Attempt is {session.status}, not submitted.")

        es = self.db.get(ExamSet, session.exam_set_id)
        question_map = {q.id: q for q in es.questions}

        correct = 0; incorrect = 0; unanswered = 0
        results: list[QuestionResultView] = []
        phase_counts: dict[int, dict] = {}

        for ans in session.answers:
            q = question_map.get(ans.question_id)
            if not q: continue
            selected = _user_selected_set(ans, q)
            if not selected:
                unanswered += 1
            elif ans.is_correct:
                correct += 1
            else:
                incorrect += 1

            slot = phase_counts.setdefault(q.topic_id, {"correct": 0, "total": 0})
            slot["total"] += 1
            if ans.is_correct:
                slot["correct"] += 1

            results.append(QuestionResultView(
                id=q.id, stem=q.stem, topic_id=q.topic_id,
                domain=q.domain, task=q.task,
                enablers=q.enablers or [], remarks=q.remarks,
                difficulty=q.difficulty,
                question_type=q.question_type,
                explanation=q.explanation,
                is_user_correct=bool(ans.is_correct),
                options=[
                    QuestionOptionResultOut(
                        option_letter=o.option_letter, text=o.text,
                        is_correct=o.is_correct, reasoning=o.reasoning,
                        selected_by_user=(o.option_letter in selected),
                    )
                    for o in q.options
                ],
            ))

        topics = {t.id: t for t in self.db.query(Topic).all()}
        by_phase = []
        for tid, v in phase_counts.items():
            t = topics.get(tid)
            by_phase.append(PhaseBreakdown(
                topic_code=t.code if t else "?",
                topic_name=t.name if t else "Unknown",
                correct=v["correct"], total=v["total"],
                percent=round((v["correct"] / v["total"]) * 100) if v["total"] else 0,
            ))
        by_phase.sort(key=lambda p: topics.get(
            next((tid for tid, t in topics.items() if t.code == p.topic_code), 0)
        ).order if any(t.code == p.topic_code for t in topics.values()) else 99)

        return SubmitAttemptOut(
            id=session.id, score=session.score or 0,
            passed=bool(session.passed),
            correct_count=correct, incorrect_count=incorrect,
            unanswered_count=unanswered,
            time_taken_seconds=session.time_taken_seconds or 0,
            questions=results, by_phase=by_phase,
        )
