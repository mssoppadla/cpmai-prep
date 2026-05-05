"""Exam attempt lifecycle: start, save answer, submit, score, result.

Critical correctness: answers + reasoning are NEVER returned during attempt.
Only the SubmitAttemptOut payload reveals them.
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.core.exceptions import (
    NotFoundError, ConflictError, ForbiddenError, SubscriptionRequiredError
)
from app.core.audit import audit_log
from app.models.user import User
from app.models.exam_set import ExamSet
from app.models.exam_session import ExamSession, ExamAttemptAnswer
from app.models.question import Question, QuestionOption
from app.models.topic import Topic
from app.models.subscription import Subscription
from app.schemas.exam import (
    ExamAttemptOut, AnswerIn, SubmitAttemptOut, PhaseBreakdown,
)
from app.schemas.exam_set import ExamSetSummaryOut
from app.schemas.question import (
    QuestionAttemptView, QuestionOptionOut,
    QuestionResultView, QuestionOptionResultOut,
)


class ExamService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ start
    def start_attempt(self, user: User, exam_set_slug: str) -> ExamAttemptOut:
        es = self.db.query(ExamSet).filter_by(slug=exam_set_slug, is_active=True).first()
        if not es:
            raise NotFoundError("Exam set not found")
        if es.is_premium and not self._has_active_subscription(user.id):
            raise SubscriptionRequiredError()
        if not es.questions:
            raise ConflictError("Exam set has no questions yet.")

        # Block multiple in-progress sessions for the same set.
        existing = self.db.query(ExamSession).filter_by(
            user_id=user.id, exam_set_id=es.id, status="in_progress",
        ).first()
        if existing and existing.expires_at > datetime.now(timezone.utc):
            return self._serialize_attempt(existing, es)

        now = datetime.now(timezone.utc)
        session = ExamSession(
            user_id=user.id,
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
        audit_log(self.db, user.id, "exam.attempt_started",
                  {"exam_set_id": es.id, "session_id": session.id})
        return self._serialize_attempt(session, es)

    # ------------------------------------------------------------------- get
    def get_attempt(self, user: User, attempt_id: int) -> ExamAttemptOut:
        session = self._load_session(user, attempt_id)
        # Auto-expire if time is up
        if session.status == "in_progress" and session.expires_at < datetime.now(timezone.utc):
            session.status = "expired"
            self.db.commit()
        es = self.db.get(ExamSet, session.exam_set_id)
        return self._serialize_attempt(session, es)

    # ---------------------------------------------------------------- answer
    def save_answer(self, user: User, attempt_id: int, payload: AnswerIn):
        session = self._load_session(user, attempt_id)
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
            raise NotFoundError("Question not part of this attempt.")
        ans.selected_letter = payload.selected_letter
        ans.marked_for_review = payload.marked_for_review
        ans.answered_at = datetime.now(timezone.utc)
        self.db.commit()

    # ---------------------------------------------------------------- submit
    def submit(self, user: User, attempt_id: int) -> SubmitAttemptOut:
        session = self._load_session(user, attempt_id)
        if session.status != "in_progress":
            raise ConflictError(f"Already {session.status}.")

        now = datetime.now(timezone.utc)
        es = self.db.get(ExamSet, session.exam_set_id)
        questions = es.questions
        question_map = {q.id: q for q in questions}

        # Build correctness map
        correct_letters: dict[int, str] = {}
        for q in questions:
            for opt in q.options:
                if opt.is_correct:
                    correct_letters[q.id] = opt.option_letter
                    break

        correct = 0; incorrect = 0; unanswered = 0
        results: list[QuestionResultView] = []
        phase_counts: dict[int, dict] = {}

        for ans in session.answers:
            q = question_map.get(ans.question_id)
            if not q:
                continue
            user_letter = ans.selected_letter
            correct_letter = correct_letters.get(q.id)
            is_correct = user_letter is not None and user_letter == correct_letter
            ans.is_correct = is_correct

            if user_letter is None:
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
                difficulty=q.difficulty, explanation=q.explanation,
                is_user_correct=is_correct,
                options=[
                    QuestionOptionResultOut(
                        option_letter=o.option_letter, text=o.text,
                        is_correct=o.is_correct, reasoning=o.reasoning,
                        selected_by_user=(o.option_letter == user_letter),
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

        audit_log(self.db, user.id, "exam.attempt_submitted",
                  {"session_id": session.id, "score": score, "passed": passed})

        return SubmitAttemptOut(
            id=session.id, score=score, passed=passed,
            correct_count=correct, incorrect_count=incorrect,
            unanswered_count=unanswered,
            time_taken_seconds=session.time_taken_seconds,
            questions=results, by_phase=by_phase,
        )

    # -------------------------------------------------------------- helpers
    def _load_session(self, user: User, attempt_id: int) -> ExamSession:
        session = self.db.get(ExamSession, attempt_id)
        if not session:
            raise NotFoundError("Attempt not found.")
        if session.user_id != user.id:
            raise ForbiddenError()
        return session

    def _has_active_subscription(self, user_id: int) -> bool:
        return bool(self.db.query(Subscription).filter_by(
            user_id=user_id, status="active",
        ).first())

    def _serialize_attempt(self, session: ExamSession, es: ExamSet) -> ExamAttemptOut:
        # Build lookup for current user answers
        user_answers = {a.question_id: a.selected_letter for a in session.answers}

        # Strip correct/reasoning from options before sending
        questions: list[QuestionAttemptView] = []
        for q in es.questions:
            questions.append(QuestionAttemptView(
                id=q.id, stem=q.stem, topic_id=q.topic_id,
                domain=q.domain, task=q.task, difficulty=q.difficulty,
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
    def get_result(self, user, attempt_id: int) -> SubmitAttemptOut:
        """Cold-load a submitted attempt's result. Reconstructs reasoning view."""
        session = self._load_session(user, attempt_id)
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
            user_letter = ans.selected_letter
            if user_letter is None:
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
                difficulty=q.difficulty, explanation=q.explanation,
                is_user_correct=bool(ans.is_correct),
                options=[
                    QuestionOptionResultOut(
                        option_letter=o.option_letter, text=o.text,
                        is_correct=o.is_correct, reasoning=o.reasoning,
                        selected_by_user=(o.option_letter == user_letter),
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
