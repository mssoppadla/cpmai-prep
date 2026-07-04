from datetime import datetime
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_admin_user, get_super_admin_user
from app.core.exceptions import AppError, NotFoundError
from app.core.audit import audit_log
from app.core.security import hash_password
from app.models.subscription import Subscription
from app.models.user import User, UserRole
from app.models.lead import Lead
from app.models.exam_session import ExamSession
from app.models.exam_set import ExamSet
from app.models.lms import Course, Chapter, Lesson, Enrollment, LessonProgress, LmsQuizAttempt
from app.models.journey_event import JourneyEvent
from app.schemas.auth import UserAdminOut

router = APIRouter()


def _user_lead_info(db: Session, users: list[User]) -> dict[int, dict]:
    """Per-user contact info from matching landing leads — LinkedIn + WhatsApp + any ALTERNATE
    email (a lead email that differs from the login email). Leads match by email OR by a browser
    ``anon_id`` the user was seen with WHILE SIGNED IN (journey_events) — so a lead submitted under
    one email and a later Google sign-in under a different email are still linked. Read-only; keyed
    by user id. Never mutates."""
    out: dict[int, dict] = {u.id: {"linkedin_id": None, "whatsapp": None, "alt_emails": []}
                            for u in users}
    if not users:
        return out
    email_to_uid = {u.email.lower(): u.id for u in users if u.email}
    uid_to_email = {u.id: (u.email or "").lower() for u in users}
    # browser ids each user was seen with while signed in (bridges different emails)
    anon_to_uids: dict[str, set[int]] = {}
    for uid, anon in (db.query(JourneyEvent.user_id, JourneyEvent.anon_id)
                      .filter(JourneyEvent.user_id.in_(list(uid_to_email.keys())),
                              JourneyEvent.anon_id.isnot(None)).distinct().all()):
        anon_to_uids.setdefault(anon, set()).add(uid)
    conds = []
    if email_to_uid:
        conds.append(func.lower(Lead.email).in_(list(email_to_uid.keys())))
    if anon_to_uids:
        conds.append(Lead.anon_id.in_(list(anon_to_uids.keys())))
    if not conds:
        return out
    for L in db.query(Lead).filter(or_(*conds)).order_by(Lead.created_at.desc()).all():
        uids: set[int] = set()
        if L.email and L.email.lower() in email_to_uid:
            uids.add(email_to_uid[L.email.lower()])
        if L.anon_id and L.anon_id in anon_to_uids:
            uids |= anon_to_uids[L.anon_id]
        for uid in uids:
            info = out[uid]
            if info["linkedin_id"] is None and L.linkedin_id:
                info["linkedin_id"] = L.linkedin_id
            if info["whatsapp"] is None and L.whatsapp_number:
                info["whatsapp"] = f"{L.country_code or ''} {L.whatsapp_number}".strip()
            if (L.email and L.email.lower() != uid_to_email.get(uid)
                    and L.email not in info["alt_emails"]):
                info["alt_emails"].append(L.email)
    return out


def active_user_ids(db: Session, active_from: datetime | None,
                    active_to: datetime | None) -> set[int] | None:
    """User ids that PERFORMED AN ACTIVITY (a journey_event) within [from, to].
    Returns None when no window is given (so callers can skip filtering)."""
    if active_from is None and active_to is None:
        return None
    jq = db.query(JourneyEvent.user_id).filter(JourneyEvent.user_id.isnot(None))
    if active_from is not None:
        jq = jq.filter(JourneyEvent.created_at >= active_from)
    if active_to is not None:
        jq = jq.filter(JourneyEvent.created_at <= active_to)
    return {r[0] for r in jq.distinct().all()}


def user_activity_window(active_from: datetime | None, active_to: datetime | None,
                         active_ids: set[int] | None):
    """A SQLAlchemy condition: the user LOGGED IN during the window OR PERFORMED an activity
    in it. Use inside a .filter() when a window is supplied."""
    login = [User.last_login_at.isnot(None)]
    if active_from is not None:
        login.append(User.last_login_at >= active_from)
    if active_to is not None:
        login.append(User.last_login_at <= active_to)
    parts = [and_(*login)]
    if active_ids:
        parts.append(User.id.in_(active_ids))
    return or_(*parts)


def _to_admin_out(u: User, sub: Subscription | None,
                  contact: dict | None = None) -> UserAdminOut:
    """Build the admin-facing user payload, including login-method and
    subscription summary so the admin UI can show everything in one row.

    The GeoIP enrichment fields (country, city, last_login_*) are
    populated by app.api.v1.endpoints.auth at signup + login time —
    we just surface them here. Nullable for users that pre-date the
    feature and for private-IP / lookup-miss cases.
    """
    return UserAdminOut(
        id=u.id, email=u.email, name=u.name, role=u.role,
        created_at=u.created_at,
        is_active=u.is_active,
        failed_login_count=u.failed_login_count,
        locked_until=u.locked_until,
        last_login_at=u.last_login_at,
        deleted_at=u.deleted_at,
        country=u.country,
        city=u.city,
        last_login_ip=u.last_login_ip,
        last_login_country=u.last_login_country,
        has_google=bool(u.google_id),
        has_password=bool(u.password_hash),
        has_active_subscription=bool(sub),
        subscription_plan=sub.plan if sub else None,
        daily_chat_limit_override=u.daily_chat_limit_override,
        linkedin_id=(contact or {}).get("linkedin_id"),
        whatsapp=(contact or {}).get("whatsapp"),
        alt_emails=((contact or {}).get("alt_emails") or None),
    )


@router.get("", response_model=list[UserAdminOut])
def list_users(db: Session = Depends(get_db),
               q: str | None = None,
               role: UserRole | None = None,
               method: str | None = Query(None, pattern="^(google|password|both)$"),
               include_deleted: bool = Query(
                   False,
                   description="If true, include soft-deleted users in the "
                               "list. Default false — admins rarely want to "
                               "see tombstones unless they're investigating "
                               "an audit/abuse case.",
               ),
               active_from: datetime | None = Query(
                   None, description="Only users who logged in OR performed an activity "
                                     "at/after this time (ISO 8601)."),
               active_to: datetime | None = Query(
                   None, description="…at/before this time. Together with active_from these "
                                     "form the activity window."),
               limit: int = Query(50, le=200),
               offset: int = 0):
    query = db.query(User)
    if active_from is not None or active_to is not None:
        query = query.filter(user_activity_window(
            active_from, active_to, active_user_ids(db, active_from, active_to)))
    if not include_deleted:
        # Default: hide soft-deleted users. They stay searchable when
        # the operator explicitly passes include_deleted=true (the
        # admin UI surfaces this as a "Show deleted" toggle).
        query = query.filter(User.deleted_at.is_(None))
    if q:
        query = query.filter(
            (User.email.ilike(f"%{q}%")) | (User.name.ilike(f"%{q}%"))
        )
    if role:
        query = query.filter(User.role == role)
    if method == "google":
        query = query.filter(User.google_id.isnot(None))
    elif method == "password":
        query = query.filter(User.password_hash.isnot(None))
    elif method == "both":
        query = query.filter(
            User.google_id.isnot(None), User.password_hash.isnot(None)
        )

    users = (query.order_by(User.id.desc()).offset(offset).limit(limit).all())
    if not users:
        return []
    # Single round-trip for active subscriptions instead of N+1.
    subs = {s.user_id: s for s in db.query(Subscription)
            .filter(Subscription.user_id.in_([u.id for u in users]),
                    Subscription.status == "active").all()}
    info = _user_lead_info(db, users)   # LinkedIn + WhatsApp + alternate emails from leads
    return [_to_admin_out(u, subs.get(u.id), info.get(u.id)) for u in users]


@router.get("/{user_id}", response_model=UserAdminOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise NotFoundError()
    sub = (db.query(Subscription)
           .filter_by(user_id=u.id, status="active").first())
    return _to_admin_out(u, sub, _user_lead_info(db, [u]).get(u.id))


@router.patch("/{user_id}/role", response_model=UserAdminOut)
def change_role(user_id: int, role: UserRole,
                db: Session = Depends(get_db),
                admin: User = Depends(get_super_admin_user)):
    u = db.get(User, user_id)
    if not u:
        raise NotFoundError()
    old = u.role
    u.role = role
    db.commit()
    db.refresh(u)
    audit_log(db, admin.id, "user.role_changed",
              {"target_user_id": user_id, "from": old.value, "to": role.value})
    sub = (db.query(Subscription)
           .filter_by(user_id=u.id, status="active").first())
    return _to_admin_out(u, sub, _user_lead_info(db, [u]).get(u.id))


class _PasswordResetIn(BaseModel):
    new_password: str = Field(min_length=8, max_length=200)


@router.patch("/{user_id}/password", response_model=UserAdminOut)
def reset_password(user_id: int, payload: _PasswordResetIn,
                   db: Session = Depends(get_db),
                   admin: User = Depends(get_super_admin_user)):
    """Super-admin force-resets a user's password.

    Operational use case: a user lost their bootstrap password, or admin
    needs to rotate the super-admin's own credential. The new value is
    accepted from the operator (not generated server-side) so they can
    type it directly into a password manager — and the response does NOT
    echo it back, so it isn't recorded in browser DevTools history.

    Audit row is written with the target user_id but NOT the password.
    """
    u = db.get(User, user_id)
    if not u:
        raise NotFoundError()
    u.password_hash = hash_password(payload.new_password)
    db.commit()
    db.refresh(u)
    audit_log(db, admin.id, "user.password_reset_by_admin",
              {"target_user_id": user_id, "target_email": u.email})
    sub = (db.query(Subscription)
           .filter_by(user_id=u.id, status="active").first())
    return _to_admin_out(u, sub, _user_lead_info(db, [u]).get(u.id))


class _ChatLimitOverrideIn(BaseModel):
    """Setting `null` clears the override; a non-negative int sets one."""
    daily_chat_limit_override: int | None = Field(default=None, ge=0, le=100000)


@router.patch("/{user_id}/chat-limit", response_model=UserAdminOut)
def set_chat_limit_override(user_id: int, payload: _ChatLimitOverrideIn,
                             db: Session = Depends(get_db),
                             admin: User = Depends(get_super_admin_user)):
    """Set or clear a user's per-day chat limit override.

    NULL = use the global `chat.daily_limit.authenticated` setting.
    Any non-negative int overrides it specifically for this user.
    Audit row captures both old and new values so we can reconstruct
    the policy history of any account.
    """
    u = db.get(User, user_id)
    if not u:
        raise NotFoundError()
    old = u.daily_chat_limit_override
    u.daily_chat_limit_override = payload.daily_chat_limit_override
    db.commit()
    db.refresh(u)
    audit_log(db, admin.id, "user.chat_limit_override_set",
              {"target_user_id": user_id, "from": old,
               "to": payload.daily_chat_limit_override})
    sub = (db.query(Subscription)
           .filter_by(user_id=u.id, status="active").first())
    return _to_admin_out(u, sub, _user_lead_info(db, [u]).get(u.id))


class _NotesIn(BaseModel):
    """Admin-only internal notes. Empty string clears them."""
    notes: str = Field(default="", max_length=20000)


@router.patch("/{user_id}/notes", response_model=UserAdminOut)
def update_notes(user_id: int, payload: _NotesIn,
                 db: Session = Depends(get_db),
                 admin: User = Depends(get_admin_user)):
    """Set or clear a user's admin-only internal notes.

    Mirrors the lead notes endpoint (``PATCH /admin/leads/{id}/notes``)
    so the unified Contacts feed can edit notes on any row — landing-form
    leads AND signed-up users alike. Plain ``get_admin_user`` gate (not
    super-admin): jotting follow-up notes is routine operator work, same
    bar as editing a lead.
    """
    u = db.get(User, user_id)
    if not u:
        raise NotFoundError()
    u.notes = payload.notes
    db.commit()
    db.refresh(u)
    audit_log(db, admin.id, "user.notes_updated",
              {"target_user_id": user_id})
    sub = (db.query(Subscription)
           .filter_by(user_id=u.id, status="active").first())
    return _to_admin_out(u, sub, _user_lead_info(db, [u]).get(u.id))


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int,
                db: Session = Depends(get_db),
                admin: User = Depends(get_super_admin_user)):
    """Soft-delete a user. Super-admin only. Cannot delete self.

    Uses the SAME redaction flow as ``DELETE /users/me`` (GDPR
    self-service deletion). Why soft-delete instead of hard:

    The User row is referenced as a FK by ~10 child tables (audit_logs,
    leads.converted_user_id, subscriptions, payments, journey_events,
    assistant_logs, exam_sessions, etc.) with NO model-level cascades.
    A hard ``db.delete(u) + db.commit()`` would fail with an integrity
    error from any of those — which is exactly the symptom reported
    on 2026-05-13: "This change conflicts with existing data — most
    often a unique field…" (our generic IntegrityError catch-all).

    Adding cascades isn't the answer either — wiping audit history +
    payment records on user delete would violate Indian tax-law
    retention (7 years on financial rows) and lose forensic data.

    Soft-delete keeps everything intact, redacts the PII, and blocks
    login. The admin can still see the row in /admin/users
    (now with email = ``deleted-{id}@redacted.invalid``), which is
    intentional — junk-account cleanup means "make this account
    unusable", not "scrub all evidence of it ever existing".

    See ``app/services/user_deletion.py`` for the full contract.
    """
    if user_id == admin.id:
        raise AppError("You cannot delete your own account.",
                       status_code=400, code="self_delete_forbidden")
    u = db.get(User, user_id)
    if not u:
        raise NotFoundError()

    # Block deleting the last super-admin to avoid locking the project out.
    if u.role == UserRole.SUPER_ADMIN:
        remaining = (db.query(User)
                     .filter(User.role == UserRole.SUPER_ADMIN,
                             User.id != user_id,
                             User.deleted_at.is_(None))
                     .count())
        if remaining == 0:
            raise AppError(
                "Cannot delete the last super-admin. Promote another user first.",
                status_code=400, code="last_super_admin",
            )

    original_email = u.email   # capture before redaction
    from app.services.user_deletion import soft_delete_user
    applied = soft_delete_user(db, u)

    audit_log(db, admin.id, "user.deleted",
              {"target_user_id": user_id,
               "email": original_email,
               "was_already_deleted": not applied,
               "mode": "soft_delete"})


@router.get("/{user_id}/insights")
def user_insights(user_id: int, db: Session = Depends(get_db)):
    """Everything an admin needs to understand ONE user's activity in a single call:
    exam attempts (count + scores + history), time spent on each part of the course, in-course
    quiz attempts, and a recent-activity timeline. Pure aggregation of existing tables."""
    u = db.get(User, user_id)
    if not u:
        raise NotFoundError()

    # --- exams: attempt count, scores, per-attempt history ---
    sessions = (db.query(ExamSession)
                .filter(ExamSession.user_id == user_id, ExamSession.status == "submitted")
                .order_by(ExamSession.submitted_at.desc().nullslast()).all())
    set_names = {s.id: s.name for s in db.query(ExamSet.id, ExamSet.name).all()}
    attempts = [{
        "id": s.id,
        "exam_set": set_names.get(s.exam_set_id),
        "practice_domain": s.practice_domain,
        "score": s.score,
        "passed": s.passed,
        "time_taken_seconds": s.time_taken_seconds,
        "submitted_at": s.submitted_at,
    } for s in sessions]
    scores = [s.score for s in sessions if s.score is not None]
    exam = {
        "attempt_count": len(sessions),
        "pass_count": sum(1 for s in sessions if s.passed),
        "best_score": max(scores) if scores else None,
        "avg_score": round(sum(scores) / len(scores)) if scores else None,
        "attempts": attempts,
    }

    # --- courses: time spent on each part (chapter), progress, quiz attempts ---
    courses = []
    quiz_attempts = 0
    for e in db.query(Enrollment).filter(Enrollment.user_id == user_id).all():
        course = db.get(Course, e.course_id)
        rows = (db.query(LessonProgress, Chapter)
                .join(Lesson, LessonProgress.lesson_id == Lesson.id)
                .join(Chapter, Lesson.chapter_id == Chapter.id)
                .filter(LessonProgress.enrollment_id == e.id).all())
        by_chapter: dict[int, dict] = {}
        completed = 0
        for lp, chapter in rows:
            c = by_chapter.setdefault(chapter.id, {
                "chapter_id": chapter.id, "title": chapter.title, "position": chapter.position,
                "watch_seconds": 0, "lessons_completed": 0, "lessons_total": 0})
            c["watch_seconds"] += lp.watch_time_seconds or 0
            c["lessons_total"] += 1
            if lp.completed_at:
                c["lessons_completed"] += 1
                completed += 1
        chapters = sorted(by_chapter.values(), key=lambda x: x["position"])
        total_lessons = (db.query(func.count(Lesson.id))
                         .join(Chapter, Lesson.chapter_id == Chapter.id)
                         .filter(Chapter.course_id == e.course_id).scalar()) or 0
        quiz_attempts += (db.query(func.count(LmsQuizAttempt.id))
                          .filter(LmsQuizAttempt.enrollment_id == e.id).scalar()) or 0
        courses.append({
            "course_id": e.course_id,
            "course_title": course.title if course else f"Course {e.course_id}",
            "enrolled_at": e.enrolled_at,
            "last_accessed_at": e.last_accessed_at,
            "completed": bool(e.completed_at),
            "total_watch_seconds": sum(c["watch_seconds"] for c in chapters),
            "lessons_completed": completed,
            "lessons_total": total_lessons,
            "progress_pct": round(100 * completed / total_lessons) if total_lessons else 0,
            "chapters": chapters,
        })

    # --- recent activity timeline ---
    events = (db.query(JourneyEvent).filter(JourneyEvent.user_id == user_id)
              .order_by(JourneyEvent.created_at.desc()).limit(50).all())
    activity = [{"event": ev.event, "path": ev.path, "duration_ms": ev.duration_ms,
                 "created_at": ev.created_at} for ev in events]

    sub = db.query(Subscription).filter_by(user_id=u.id, status="active").first()
    return {
        "user": _to_admin_out(u, sub, _user_lead_info(db, [u]).get(u.id)),
        "exam": exam,
        "courses": courses,
        "quiz_attempts": quiz_attempts,
        "activity": activity,
    }
