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
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func, case
from sqlalchemy.exc import IntegrityError
from app.core.exceptions import (
    NotFoundError, ConflictError, ForbiddenError, SubscriptionRequiredError,
    UnauthorizedError,
)
from app.core.audit import audit_log
from app.core import domains as domain_registry
from app.services.tracking_service import emit_event
from app.models.user import User
from app.models.exam_set import ExamSet, ExamSetQuestion
from app.models.exam_session import ExamSession, ExamAttemptAnswer
from app.models.question import Question, QuestionOption, QuestionType
from app.models.topic import Topic
from app.models.subscription import Subscription
from app.models.plan import PlanExamSet
from app.schemas.exam import (
    ExamAttemptOut, AnswerIn, SubmitAttemptOut, PhaseBreakdown, DomainBreakdown,
    AttemptHistoryOut,
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


# The CPMAI ECO is organised by domain, so results are rolled up by the
# question's `domain` rather than by phase/topic. Questions with no domain
# fall into this bucket, which is always sorted last.
UNASSIGNED_DOMAIN = "Unassigned"


def _domain_label_raw(domain: str | None) -> str:
    """Canonical grouping key for a stored domain value. Resolves legacy
    spellings (name/slug/free-text) to the ECO domain code so groups
    merge; keeps unrecognised free-text as-is; falls back to
    'Unassigned' when blank."""
    d = domain_registry.get(domain)
    if d:
        return d.code
    raw = (domain or "").strip()
    return raw or UNASSIGNED_DOMAIN


def _domain_label(question) -> str:
    return _domain_label_raw(question.domain)


def _build_domain_breakdown(domain_counts: dict[str, dict]) -> list[DomainBreakdown]:
    """Turn a {domain: {correct, total}} tally into sorted DomainBreakdowns.
    Ordered by the ECO domain order, then alphabetically, with 'Unassigned'
    pinned last."""
    rows = [
        DomainBreakdown(
            domain=label,
            domain_name=domain_registry.display_name(label),
            practiceable=domain_registry.is_valid_code(label),
            correct=v["correct"], total=v["total"],
            percent=round((v["correct"] / v["total"]) * 100) if v["total"] else 0,
        )
        for label, v in domain_counts.items()
    ]

    def sort_key(r: DomainBreakdown):
        d = domain_registry.get(r.domain)
        order = d.order if d else 98  # known domains first, in ECO order
        if r.domain == UNASSIGNED_DOMAIN:
            order = 99
        return (order, r.domain_name.lower())

    rows.sort(key=sort_key)
    return rows


def _build_phase_breakdown(db: Session,
                           phase_counts: dict[int, dict]) -> list[PhaseBreakdown]:
    """Turn a {topic_id: {correct, total}} tally into PhaseBreakdowns
    sorted in CPMAI phase order (unknown topics last)."""
    topics = {t.id: t for t in db.query(Topic).all()}
    rows = [
        PhaseBreakdown(
            topic_code=topics[tid].code if tid in topics else "?",
            topic_name=topics[tid].name if tid in topics else "Unknown",
            correct=v["correct"], total=v["total"],
            percent=round((v["correct"] / v["total"]) * 100) if v["total"] else 0,
        )
        for tid, v in phase_counts.items()
    ]
    order_by_code = {t.code: t.order for t in topics.values()}
    rows.sort(key=lambda p: order_by_code.get(p.topic_code, 99))
    return rows


class ExamService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------ access guard
    def _load_set_for_attempt(self, actor: "User | str | None",
                              exam_set_slug: str) -> ExamSet:
        """Load an active set and enforce the same access rules every
        attempt path shares (auth presence + premium paywall). Does NOT
        check emptiness — callers decide what "empty" means (a full set
        vs a domain-filtered subset)."""
        if actor is None:
            raise UnauthorizedError(
                "Provide an Authorization header or X-Anon-Token to start.",
            )
        # Eager-load questions AND their options in 3 queries total.
        # The default lazy loading made every attempt start / serialize
        # fire one extra query PER QUESTION for its options (~60 queries
        # per start on a full set) — a pool-exhausting burst when a
        # cohort starts together (perf review 2026-08-07).
        es = (self.db.query(ExamSet)
              .options(selectinload(ExamSet.questions)
                       .selectinload(Question.options))
              .filter_by(slug=exam_set_slug, is_active=True).first())
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
        return es

    # ------------------------------------------------------------------ start
    # Pause-on-leave timer: an activity gap is charged at most this much,
    # so a lost pause beacon (tab crash, power cut, offline close) can
    # never bill the hours the candidate was away. 3× the frontend's 30s
    # heartbeat — one missed beat plus jitter is still fully charged;
    # anything longer means the page wasn't open.
    ACTIVITY_CHARGE_CAP_SECONDS = 90

    def _charge_activity(self, session: "ExamSession",
                         now: "datetime | None" = None) -> None:
        """Debit active time since the last activity event (capped) and
        re-anchor the wall-clock deadline so in-exam expiry checks and
        the frontend countdown keep working off expires_at. Callers
        commit. Also the resume path: a resume after days away charges
        at most the cap, which is exactly the pause semantics."""
        now = now or datetime.now(timezone.utc)
        if session.remaining_seconds is None:
            # Legacy row (pre-0046): convert its current wall-clock
            # remainder into an active-time budget once.
            session.remaining_seconds = max(
                0, int((session.expires_at - now).total_seconds()))
        else:
            elapsed = ((now - session.last_activity_at).total_seconds()
                       if session.last_activity_at else 0.0)
            charge = int(min(max(elapsed, 0.0),
                             self.ACTIVITY_CHARGE_CAP_SECONDS))
            session.remaining_seconds = max(
                0, session.remaining_seconds - charge)
        session.last_activity_at = now
        session.expires_at = now + timedelta(
            seconds=session.remaining_seconds)

    def _draft_is_live(self, session: "ExamSession",
                       now: "datetime | None" = None) -> bool:
        """Resumable = in_progress with active-time budget left. The
        paused clock means expires_at goes stale while the candidate is
        away — NEVER use expires_at alone to judge liveness."""
        if session.status != "in_progress":
            return False
        if session.remaining_seconds is not None:
            return session.remaining_seconds > 0
        # Legacy row: old wall-clock rule until first activity converts it.
        return session.expires_at > (now or datetime.now(timezone.utc))

    def _has_any_answer(self, session_id: int) -> bool:
        return self.db.query(ExamAttemptAnswer.id).filter(
            ExamAttemptAnswer.exam_session_id == session_id,
            (ExamAttemptAnswer.selected_letter.isnot(None))
            | (ExamAttemptAnswer.selected_letters.isnot(None)),
        ).first() is not None

    def _adopt_orphan_draft(self, user: "User", exam_set_id: int,
                            anon_token: str | None,
                            practice_domain: str | None) -> "ExamSession | None":
        """Claim an anon-owned in-progress draft for a signed-in user.

        Healing path for the expired-token incident (2026-08-07): a draft
        created while the user's access token had silently expired was
        owned by their browser's anon token, so their signed-in identity
        could never save to it or resume it. When the same browser (same
        anon token) starts the set while signed in, transfer the draft to
        the account instead of stranding the answers on an unreachable
        session.
        """
        if not anon_token:
            return None
        orphan = self.db.query(ExamSession).filter_by(
            anon_token=anon_token, exam_set_id=exam_set_id,
            status="in_progress", practice_domain=practice_domain,
            user_id=None,
        ).first()
        if not orphan:
            return None
        orphan.user_id = user.id
        orphan.anon_token = None
        self.db.commit()
        audit_log(self.db, user.id, "exam.attempt_adopted",
                  {"exam_set_id": exam_set_id, "session_id": orphan.id})
        return orphan

    def start_attempt(self, actor: "User | str | None",
                      exam_set_slug: str,
                      anon_token: str | None = None) -> ExamAttemptOut:
        es = self._load_set_for_attempt(actor, exam_set_slug)
        if not es.questions:
            raise ConflictError("Exam set has no questions yet.")

        # Block multiple in-progress sessions for the same set, scoped to the
        # caller (a logged-in user gets one session per set; an anon token
        # gets one session per set per browser). `practice_domain IS NULL`
        # keeps full-set sittings distinct from domain-practice sessions on
        # the same set — resuming one must never resume the other.
        if isinstance(actor, User):
            existing_q = self.db.query(ExamSession).filter_by(
                user_id=actor.id, exam_set_id=es.id, status="in_progress",
                practice_domain=None,
            )
        else:
            existing_q = self.db.query(ExamSession).filter_by(
                anon_token=actor, exam_set_id=es.id, status="in_progress",
                practice_domain=None,
            )
        existing = existing_q.first()
        if existing is None and isinstance(actor, User):
            existing = self._adopt_orphan_draft(actor, es.id, anon_token, None)
        if existing and self._draft_is_live(existing):
            # Resume: re-anchor the paused clock (charges at most the
            # activity cap for the pre-pause gap, never the time away).
            self._charge_activity(existing)
            self.db.commit()
            # Backfill answer rows for any questions added to the set
            # AFTER this session started, so they're answerable now.
            self._ensure_answer_rows(existing, es)
            return self._serialize_attempt(existing, es)
        if existing and not self._draft_is_live(existing) \
                and not self._has_any_answer(existing.id):
            # A timed-out draft with NOTHING answered has no result worth
            # freezing — mark abandoned instead of minting a 0% history
            # row. Marked, never deleted: exam_sessions is a guarded
            # table and deploy.sh aborts when guarded rows disappear
            # (incident 2026-08-07).
            existing.status = "abandoned"
            self.db.commit()

        now = datetime.now(timezone.utc)
        session = ExamSession(
            user_id=actor.id if isinstance(actor, User) else None,
            anon_token=None if isinstance(actor, User) else actor,
            exam_set_id=es.id,
            started_at=now,
            expires_at=now + timedelta(minutes=es.time_limit_minutes),
            remaining_seconds=es.time_limit_minutes * 60,
            last_activity_at=now,
            status="in_progress",
        )
        self.db.add(session)
        try:
            self.db.flush()
        except IntegrityError:
            # A concurrent /start (double-click, retried request) won the
            # race and created the draft first — the partial unique index
            # uq_one_live_draft_per_user_set rejects this second insert.
            # Resume the winner instead of erroring; duplicate drafts are
            # what minted the 0%-row flood before (migration 0046).
            self.db.rollback()
            winner = existing_q.first()
            if winner is None:
                raise
            self._ensure_answer_rows(winner, es)
            return self._serialize_attempt(winner, es)
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

    # -------------------------------------------------------------- history
    def list_attempts(self, user: "User") -> list[AttemptHistoryOut]:
        """The signed-in user's attempts, newest first: submitted results
        AND live drafts (status="in_progress"), so the dashboard can show
        a draft row + a latest-result row per set and the attempts-manager
        window can list every instance. Anonymous attempts are
        intentionally excluded (they aren't bound to an account). Counts
        come from one grouped query over the answer rows, so this stays
        O(1) round-trips."""
        now = datetime.now(timezone.utc)
        sessions = (self.db.query(ExamSession)
                    .filter(ExamSession.user_id == user.id,
                            ExamSession.status.in_(["in_progress",
                                                    "submitted"]))
                    .order_by(ExamSession.submitted_at.desc().nullslast(),
                              ExamSession.id.desc())
                    .all())
        # Timed-out drafts are handled on sight (same lazy rule as
        # get_result): NOTHING answered → discarded outright (a 0% row
        # nobody sat is noise, not history — the 2026-08-07 backlog
        # minted dozens); something answered → finalized as
        # auto-submitted. Finalization builds a full result snapshot,
        # so it's capped per request — the remainder waits for the next
        # view instead of stalling this one.
        _FINALIZE_CAP = 10
        finalized = 0
        kept: list[ExamSession] = []
        for s in sessions:
            if s.status == "in_progress" and not self._draft_is_live(s, now):
                if not self._has_any_answer(s.id):
                    s.status = "abandoned"   # marked, never deleted
                    self.db.commit()
                    continue
                if finalized < _FINALIZE_CAP:
                    self._finalize(s, auto=True)
                    finalized += 1
                else:
                    continue  # over cap — surfaces next call
            kept.append(s)
        sessions = kept
        if not sessions:
            return []
        sids = [s.id for s in sessions]
        set_ids = {s.exam_set_id for s in sessions if s.exam_set_id}
        sets = ({es.id: es for es in self.db.query(ExamSet)
                 .filter(ExamSet.id.in_(set_ids)).all()} if set_ids else {})
        rows = (self.db.query(
                    ExamAttemptAnswer.exam_session_id,
                    func.count(ExamAttemptAnswer.id),
                    func.sum(case((ExamAttemptAnswer.is_correct.is_(True), 1),
                                  else_=0)))
                .filter(ExamAttemptAnswer.exam_session_id.in_(sids))
                .group_by(ExamAttemptAnswer.exam_session_id).all())
        counts = {sid: (total, int(correct or 0)) for sid, total, correct in rows}
        out: list[AttemptHistoryOut] = []
        for s in sessions:
            es = sets.get(s.exam_set_id)
            total, correct = counts.get(s.id, (0, 0))
            out.append(AttemptHistoryOut(
                id=s.id,
                exam_set_name=es.name if es else None,
                exam_set_slug=es.slug if es else None,
                practice_domain=s.practice_domain,
                status=s.status,
                auto_submitted=bool(s.auto_submitted),
                remaining_seconds=(s.remaining_seconds
                                   if s.status == "in_progress" else None),
                score=s.score or 0,
                passed=bool(s.passed),
                total_questions=total,
                correct_count=correct,
                time_taken_seconds=s.time_taken_seconds or 0,
                submitted_at=s.submitted_at,
                expires_at=s.expires_at,
            ))
        return out

    # -------------------------------------------------------- domain practice
    def start_domain_practice(self, actor: "User | str | None",
                              exam_set_slug: str,
                              domain_code: str,
                              anon_token: str | None = None) -> ExamAttemptOut:
        """Start (or resume) a focused practice attempt over the questions
        of one ECO domain *within a set the caller already has access to*.

        Reached from the results screen: after a full sitting, a learner
        drills into a domain they scored low on. Access rules mirror the
        full-set path (premium paywall still applies), and the question
        pool is the set's own questions filtered to `domain_code` — so a
        premium set's questions are never exposed outside its paywall.
        """
        domain = domain_registry.get(domain_code)
        if not domain:
            raise NotFoundError(f"Unknown domain {domain_code!r}.")
        es = self._load_set_for_attempt(actor, exam_set_slug)
        scoped = [q for q in es.questions if _domain_label(q) == domain.code]
        if not scoped:
            raise ConflictError(
                f"This set has no '{domain.name}' questions to practice yet.")

        # Resume an in-progress practice for the SAME (caller, set, domain).
        if isinstance(actor, User):
            existing_q = self.db.query(ExamSession).filter_by(
                user_id=actor.id, exam_set_id=es.id, status="in_progress",
                practice_domain=domain.code,
            )
        else:
            existing_q = self.db.query(ExamSession).filter_by(
                anon_token=actor, exam_set_id=es.id, status="in_progress",
                practice_domain=domain.code,
            )
        existing = existing_q.first()
        if existing is None and isinstance(actor, User):
            existing = self._adopt_orphan_draft(actor, es.id, anon_token,
                                                domain.code)
        if existing and self._draft_is_live(existing):
            self._charge_activity(existing)
            self.db.commit()
            self._ensure_answer_rows(existing, es)
            return self._serialize_attempt(existing, es)
        if existing and not self._draft_is_live(existing) \
                and not self._has_any_answer(existing.id):
            self.db.delete(existing)
            self.db.commit()

        now = datetime.now(timezone.utc)
        # Allow ~1.5 min/question (min 5), independent of the full set's
        # clock — a domain drill is shorter than a full sitting.
        minutes = max(5, round(len(scoped) * 1.5))
        session = ExamSession(
            user_id=actor.id if isinstance(actor, User) else None,
            anon_token=None if isinstance(actor, User) else actor,
            exam_set_id=es.id,
            practice_domain=domain.code,
            started_at=now,
            expires_at=now + timedelta(minutes=minutes),
            remaining_seconds=minutes * 60,
            last_activity_at=now,
            status="in_progress",
        )
        self.db.add(session)
        try:
            self.db.flush()
        except IntegrityError:
            # Concurrent start for the same drill — resume the winner
            # (see the full-set path for the full rationale).
            self.db.rollback()
            winner = existing_q.first()
            if winner is None:
                raise
            self._ensure_answer_rows(winner, es)
            return self._serialize_attempt(winner, es)
        for q in scoped:
            self.db.add(ExamAttemptAnswer(
                exam_session_id=session.id, question_id=q.id,
            ))
        self.db.commit()
        self.db.refresh(session)
        actor_user_id = actor.id if isinstance(actor, User) else None
        audit_log(self.db, actor_user_id, "exam.domain_practice_started",
                  {"exam_set_id": es.id, "session_id": session.id,
                   "domain": domain.code, "question_count": len(scoped),
                   "anonymous": actor_user_id is None})
        emit_event(self.db, "exam.started", user_id=actor_user_id,
                   metadata={"exam_set_id": es.id, "exam_set_slug": es.slug,
                             "exam_session_id": session.id,
                             "practice_domain": domain.code,
                             "is_premium": es.is_premium,
                             "anonymous": actor_user_id is None})
        return self._serialize_attempt(session, es)

    # --------------------------------------------------- attempt question pool
    def _attempt_questions(self, session: "ExamSession",
                           es: "ExamSet") -> list[Question]:
        """The questions that belong to THIS attempt, in set order.

        Full sitting → every question in the set. Domain practice → only
        the set's questions whose domain matches `session.practice_domain`.
        Single source of truth for serialization and answer-row backfill."""
        if session.practice_domain:
            return [q for q in es.questions
                    if _domain_label(q) == session.practice_domain]
        return list(es.questions)

    # ------------------------------------------------------------------- get
    def get_attempt(self, actor: "User | str | None",
                    attempt_id: int) -> ExamAttemptOut:
        session = self._load_session(actor, attempt_id)
        # Time up → auto-submit. The sitting is finalized with whatever
        # was answered (the rest counts as unanswered) so the result is
        # always captured — a time-out never voids the attempt.
        if session.status == "in_progress" and \
                session.expires_at < datetime.now(timezone.utc):
            self._finalize(session)
        es = self.db.get(ExamSet, session.exam_set_id)
        return self._serialize_attempt(session, es)

    # ---------------------------------------------------------------- answer
    def save_answer(self, actor: "User | str | None",
                    attempt_id: int, payload: AnswerIn):
        session = self._load_session(actor, attempt_id)
        if session.status != "in_progress":
            raise ConflictError(f"Cannot modify a {session.status} attempt.")
        # Charge active time first, then judge expiry off the budget —
        # a save doubles as the activity heartbeat.
        self._charge_activity(session)
        if session.remaining_seconds is not None \
                and session.remaining_seconds <= 0:
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

    # ------------------------------------------------------- timer events
    def heartbeat(self, actor: "User | str | None",
                  attempt_id: int) -> int:
        """Charge active screen time and return the remaining budget.
        Fired every 30s by the exam page while visible, and once via
        keepalive fetch on leave (the pause signal — pausing IS simply
        the absence of further charges). Idempotent and cheap: one row
        update. Returns 0 for already-finalized attempts so a late
        beacon never errors."""
        session = self._load_session(actor, attempt_id)
        if session.status != "in_progress":
            return 0
        self._charge_activity(session)
        self.db.commit()
        return session.remaining_seconds or 0

    # ---------------------------------------------------------------- submit
    def submit(self, actor: "User | str | None",
               attempt_id: int, auto: bool = False) -> SubmitAttemptOut:
        """Finalize a sitting and freeze its result.

        Accepts BOTH `in_progress` and `expired` attempts: when the
        clock runs out the answers the candidate saved are still the
        candidate's answers, so time-up finalizes the sitting instead
        of voiding it (unanswered questions simply count as
        unanswered). Only an already-finalized attempt is rejected.
        `auto=True` marks a clock-driven submit (the exam page's
        time-up path) so the history row is labeled honestly."""
        session = self._load_session(actor, attempt_id)
        if session.status not in ("in_progress", "expired"):
            raise ConflictError(f"Already {session.status}.")
        return self._finalize(session, auto=auto)

    def _finalize(self, session: "ExamSession",
                  auto: bool = False) -> SubmitAttemptOut:
        """Score the sitting from its saved answers and freeze the
        result (status, score, snapshot). Callers own the status guard;
        this is also invoked directly by the read paths to auto-submit
        timed-out attempts (where the actor may be an admin viewing
        someone else's attempt, so re-loading by actor is wrong).
        `auto=True` = clock-driven finalization: sets the explicit
        auto_submitted flag and stamps submitted_at with the last time
        the candidate actually touched the sitting — not the moment the
        lazy sweep happened to run (the 2026-08-07 backlog flood showed
        every row time-stamped with the sweep minute)."""
        now = datetime.now(timezone.utc)
        es = self.db.get(ExamSet, session.exam_set_id)
        questions = es.questions
        question_map = {q.id: q for q in questions}

        correct = 0; incorrect = 0; unanswered = 0
        results: list[QuestionResultView] = []
        phase_counts: dict[int, dict] = {}
        domain_counts: dict[str, dict] = {}

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

            # Per-domain tally (what the results screen surfaces)
            dslot = domain_counts.setdefault(_domain_label(q), {"correct": 0, "total": 0})
            dslot["total"] += 1
            if is_correct:
                dslot["correct"] += 1

            # Build result view (full reveal)
            results.append(QuestionResultView(
                id=q.id, stem=q.stem, topic_id=q.topic_id,
                domain=q.domain, task=q.task,
                enablers=q.enablers or [], remarks=q.remarks,
                difficulty=q.difficulty,
                question_type=q.question_type,
                explanation=q.explanation,
                is_user_correct=is_correct,
                marked_for_review=bool(ans.marked_for_review),
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

        # A time-up submit (auto or late) never reports more time than
        # the sitting actually allowed.
        timed_out = now >= session.expires_at
        session.status = "submitted"
        session.auto_submitted = auto
        # Honest stamp for clock-driven finalization: the candidate's
        # last activity (fallback: the stale deadline), never the sweep
        # time.
        session.submitted_at = (
            (session.last_activity_at or session.expires_at)
            if auto else now)
        session.score = score
        session.passed = passed
        session.time_taken_seconds = min(
            int((now - session.started_at).total_seconds()),
            int((session.expires_at - session.started_at).total_seconds()),
        )
        # Freeze the full review payload as sat: later edits to the live
        # questions (reworded stems, changed answer keys, removals from
        # the set) must not rewrite what this candidate actually saw.
        # get_result serves this snapshot; live reconstruction remains
        # only for attempts submitted before the column existed.
        session.result_snapshot = [r.model_dump(mode="json") for r in results]
        self.db.commit()

        by_phase = _build_phase_breakdown(self.db, phase_counts)

        actor_user_id = session.user_id  # None for anon
        audit_log(self.db, actor_user_id, "exam.attempt_submitted",
                  {"session_id": session.id, "score": score, "passed": passed,
                   "anonymous": actor_user_id is None,
                   "timed_out": timed_out})
        emit_event(self.db, "exam.submitted", user_id=actor_user_id,
                   metadata={"exam_set_id": es.id if es else None,
                             "exam_session_id": session.id,
                             "score": score, "passed": passed,
                             "correct": correct, "incorrect": incorrect,
                             "unanswered": unanswered,
                             "anonymous": actor_user_id is None})

        # Lifecycle email automations (fail-soft; signed-in users only —
        # anonymous attempts have no email address to write to).
        if actor_user_id is not None:
            from app.models.user import User as _User
            from app.services.email.automation import enqueue_for_trigger
            _u = self.db.get(_User, actor_user_id)
            if _u is not None:
                enqueue_for_trigger(
                    self.db, "exam.submitted", _u,
                    event_ref=f"exam{session.id}",
                    context_extra={
                        "exam_title": es.name if es else "",
                        "score": str(score),
                        "passed": "passed" if passed else "not passed",
                        "attempt_date": now.strftime("%d %b %Y"),
                    })

        return SubmitAttemptOut(
            id=session.id, score=score, passed=passed,
            correct_count=correct, incorrect_count=incorrect,
            unanswered_count=unanswered,
            time_taken_seconds=session.time_taken_seconds,
            questions=results, by_phase=by_phase,
            by_domain=_build_domain_breakdown(domain_counts),
            exam_set_slug=es.slug if es else None,
            exam_set_name=es.name if es else None,
            practice_domain=session.practice_domain,
        )

    def delete_attempt(self, actor: "User | str | None",
                       attempt_id: int, admin: bool = False) -> None:
        """Remove an attempt from the owner's history (any status).

        Owner path: a user prunes their history, or discards an
        in-progress draft to start the set fresh. Anonymous attempts are
        removable by the matching X-Anon-Token holder. Admin path: an
        admin removes an attempt while reviewing a candidate's exam
        details (endpoint is admin-gated).

        SOFT removal by design. `exam_sessions` and
        `exam_attempt_answers` are GUARDED_TABLES — deploy.sh aborts and
        auto-rolls-back when a guarded table loses rows, so a hard
        DELETE here would turn "a user tidied their history during a
        deploy window" into a failed production deploy (the same guard
        that stopped migration 0046 on 2026-08-07). Marked rows are
        filtered out of every read path, so the attempt is gone as far
        as users and admins are concerned; account-level erasure stays
        with the GDPR delete-account flow.
        """
        session = self._load_session(actor, attempt_id, admin=admin)
        session.status = "deleted"
        self.db.commit()

    # -------------------------------------------------------------- helpers
    def _ensure_answer_rows(self, session: "ExamSession", es: "ExamSet") -> None:
        """Make sure there's a one-to-one mapping between this attempt's
        questions and answer rows. Creates rows for any in-scope question
        added to the set after this session began. Scope respects domain
        practice — a drill never back-fills the whole set."""
        existing = {a.question_id for a in self.db.query(ExamAttemptAnswer)
                    .filter_by(exam_session_id=session.id).all()}
        added = 0
        for q in self._attempt_questions(session, es):
            if q.id in existing:
                continue
            self.db.add(ExamAttemptAnswer(
                exam_session_id=session.id, question_id=q.id,
            ))
            added += 1
        if added:
            self.db.commit()

    def _load_session(self, actor: "User | str | None",
                      attempt_id: int, admin: bool = False) -> ExamSession:
        session = self.db.get(ExamSession, attempt_id)
        if not session:
            raise NotFoundError("Attempt not found.")
        # Soft-removed sittings are gone as far as every caller is
        # concerned (see delete_attempt for why rows survive).
        if session.status in ("deleted", "abandoned"):
            raise NotFoundError("Attempt not found.")
        if admin:
            return session          # admin support view: any user's attempt (endpoint is admin-gated)
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
        # revoked_at column ships in migration 0022 — once an admin
        # revokes (e.g. after issuing a refund), the sub no longer
        # grants paywall access regardless of expires_at.
        subs = (self.db.query(Subscription)
                .filter(Subscription.user_id == user_id,
                        Subscription.status == "active",
                        Subscription.revoked_at.is_(None),
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
        # Only the questions in THIS attempt's scope (full set, or one
        # domain for a practice drill).
        scoped = self._attempt_questions(session, es)
        scoped_ids = {q.id for q in scoped}

        # Per-question current selection. Single-choice → letter | None.
        # Multi-choice → comma-joined sorted letters | None (so the wire
        # type stays `dict[int, str | None]` and the frontend just splits
        # on ',' for multi questions). Empty selection → None either way.
        question_by_id = {q.id: q for q in scoped}
        user_answers: dict[int, str | None] = {}
        for a in session.answers:
            if a.question_id not in scoped_ids:
                continue  # stray row from a since-removed question
            q = question_by_id[a.question_id]
            if q.question_type == QuestionType.MULTI_CHOICE:
                letters = a.selected_letters or []
                user_answers[a.question_id] = (",".join(sorted(letters))
                                                if letters else None)
            else:
                user_answers[a.question_id] = a.selected_letter

        # Strip correct/reasoning from options before sending
        questions: list[QuestionAttemptView] = []
        for q in scoped:
            questions.append(QuestionAttemptView(
                id=q.id, stem=q.stem, topic_id=q.topic_id,
                domain=q.domain, task=q.task, difficulty=q.difficulty,
                question_type=q.question_type,
                options=[QuestionOptionOut(option_letter=o.option_letter, text=o.text)
                         for o in q.options],
            ))

        # For a domain drill, annotate the set name so the attempt header
        # reads e.g. "Set 2 · Practice: Trustworthy AI".
        display_name = es.name
        if session.practice_domain:
            dn = domain_registry.display_name(session.practice_domain)
            display_name = f"{es.name} · Practice: {dn}"

        return ExamAttemptOut(
            id=session.id,
            exam_set=ExamSetSummaryOut(
                id=es.id, name=display_name, slug=es.slug, description=es.description,
                difficulty=es.difficulty, time_limit_minutes=es.time_limit_minutes,
                passing_score=es.passing_score, is_premium=es.is_premium,
                cover_image_url=es.cover_image_url,
                question_count=len(scoped),
            ),
            started_at=session.started_at, expires_at=session.expires_at,
            status=session.status, questions=questions,
            user_answers=user_answers,
        )

    # ---------------------------------------------------------------- result
    def get_result(self, actor: "User | str | None",
                   attempt_id: int, admin: bool = False) -> SubmitAttemptOut:
        """Cold-load a submitted attempt's result. Reconstructs reasoning view.
        admin=True (via the admin-gated endpoint) lets a support/admin view ANY user's attempt."""
        session = self._load_session(actor, attempt_id, admin=admin)
        # A timed-out sitting that was never explicitly submitted is
        # finalized on first view — the result is captured, not lost.
        # (Liveness is budget-based: a PAUSED draft with time left is
        # NOT timed out even though its wall-clock expires_at is stale.)
        now = datetime.now(timezone.utc)
        if session.status == "expired" or (
                session.status == "in_progress"
                and not self._draft_is_live(session, now)):
            self._finalize(session, auto=True)
        if session.status != "submitted":
            raise ConflictError(f"Attempt is {session.status}, not submitted.")

        es = self.db.get(ExamSet, session.exam_set_id)

        # Attempts submitted since the snapshot column exists replay the
        # frozen payload — the review shows exactly what the candidate
        # sat, regardless of how the live questions/set changed since.
        if session.result_snapshot:
            return self._result_from_snapshot(session, es)

        # Legacy attempts (no snapshot): reconstruct from live questions.
        question_map = {q.id: q for q in es.questions}

        correct = 0; incorrect = 0; unanswered = 0
        results: list[QuestionResultView] = []
        phase_counts: dict[int, dict] = {}
        domain_counts: dict[str, dict] = {}

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

            dslot = domain_counts.setdefault(_domain_label(q), {"correct": 0, "total": 0})
            dslot["total"] += 1
            if ans.is_correct:
                dslot["correct"] += 1

            results.append(QuestionResultView(
                id=q.id, stem=q.stem, topic_id=q.topic_id,
                domain=q.domain, task=q.task,
                enablers=q.enablers or [], remarks=q.remarks,
                difficulty=q.difficulty,
                question_type=q.question_type,
                explanation=q.explanation,
                is_user_correct=bool(ans.is_correct),
                marked_for_review=bool(ans.marked_for_review),
                options=[
                    QuestionOptionResultOut(
                        option_letter=o.option_letter, text=o.text,
                        is_correct=o.is_correct, reasoning=o.reasoning,
                        selected_by_user=(o.option_letter in selected),
                    )
                    for o in q.options
                ],
            ))

        return SubmitAttemptOut(
            id=session.id, score=session.score or 0,
            passed=bool(session.passed),
            correct_count=correct, incorrect_count=incorrect,
            unanswered_count=unanswered,
            time_taken_seconds=session.time_taken_seconds or 0,
            questions=results,
            by_phase=_build_phase_breakdown(self.db, phase_counts),
            by_domain=_build_domain_breakdown(domain_counts),
            exam_set_slug=es.slug if es else None,
            exam_set_name=es.name if es else None,
            practice_domain=session.practice_domain,
        )

    def _result_from_snapshot(self, session: "ExamSession",
                              es: "ExamSet | None") -> SubmitAttemptOut:
        """Rebuild a submitted attempt's result from the frozen snapshot
        taken at submit. Counts and breakdowns are derived from the
        snapshot itself (not live questions), so the whole result stays
        internally consistent with the stored score forever."""
        results = [QuestionResultView(**item) for item in session.result_snapshot]

        # Overlay "marked for review" from the answer rows: snapshots
        # frozen before the field existed (incl. the 0044 backfill)
        # don't carry it, but the flag survives on ExamAttemptAnswer.
        # The snapshot value is the fallback for answers deleted since
        # (e.g. when the question itself was removed).
        marked = {a.question_id: bool(a.marked_for_review)
                  for a in session.answers}
        for r in results:
            if r.id in marked:
                r.marked_for_review = marked[r.id]

        correct = 0; incorrect = 0; unanswered = 0
        phase_counts: dict[int, dict] = {}
        domain_counts: dict[str, dict] = {}
        for r in results:
            answered = any(o.selected_by_user for o in r.options)
            if not answered:
                unanswered += 1
            elif r.is_user_correct:
                correct += 1
            else:
                incorrect += 1

            slot = phase_counts.setdefault(r.topic_id, {"correct": 0, "total": 0})
            slot["total"] += 1
            if r.is_user_correct:
                slot["correct"] += 1

            dslot = domain_counts.setdefault(_domain_label_raw(r.domain),
                                             {"correct": 0, "total": 0})
            dslot["total"] += 1
            if r.is_user_correct:
                dslot["correct"] += 1

        return SubmitAttemptOut(
            id=session.id, score=session.score or 0,
            passed=bool(session.passed),
            correct_count=correct, incorrect_count=incorrect,
            unanswered_count=unanswered,
            time_taken_seconds=session.time_taken_seconds or 0,
            questions=results,
            by_phase=_build_phase_breakdown(self.db, phase_counts),
            by_domain=_build_domain_breakdown(domain_counts),
            exam_set_slug=es.slug if es else None,
            exam_set_name=es.name if es else None,
            practice_domain=session.practice_domain,
        )
