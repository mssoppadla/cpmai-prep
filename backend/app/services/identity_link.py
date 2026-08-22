"""Claim-on-login: attach a browser's anonymous history to the account.

Called from every successful auth entry point (signup, login, Google)
with the request's X-Anon-ID — the browser's persistent localStorage id
(``cpmai.anon_token``), which is ALSO the token that owns anonymous
exam attempts. One id, three claims:

  1. Record/refresh the anon_id → user link (anon_identity_links).
     A shared browser re-links to the most recent login; already-
     backfilled history keeps its original owner.
  2. Backfill user_id onto this browser's anonymous journey_events —
     the visitor's pre-login page views join their account timeline.
  3. Claim FINISHED anonymous exam attempts (submitted/abandoned) so
     results taken before login appear in the profile. In-progress
     drafts are deliberately left to the existing _adopt_orphan_draft
     path — claiming a live draft here could collide with the
     uq_one_live_draft_per_user_set index when the account already has
     its own draft for the same set.

Fail-soft: linking must never break a login. UPDATEs only — no
deletes; journey_events and exam_sessions are guarded tables.
"""
import structlog
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.models.anon_identity_link import AnonIdentityLink
from app.models.exam_session import ExamSession
from app.models.journey_event import JourneyEvent
from app.models.user import User

log = structlog.get_logger()


def link_identity(db: Session, user: User, anon_id: str | None) -> None:
    if not anon_id:
        return
    anon_id = str(anon_id)[:36]
    try:
        link = (db.query(AnonIdentityLink)
                .filter_by(anon_id=anon_id).first())
        newly_linked = link is None
        if link is None:
            link = AnonIdentityLink(anon_id=anon_id, user_id=user.id)
            db.add(link)
        elif link.user_id != user.id:
            # Shared browser, different account: most recent login owns
            # future attribution. History already claimed stays put.
            link.user_id = user.id
            newly_linked = True

        journey_rows = (db.query(JourneyEvent)
                        .filter(JourneyEvent.anon_id == anon_id,
                                JourneyEvent.user_id.is_(None))
                        .update({JourneyEvent.user_id: user.id},
                                synchronize_session=False))

        # Finished attempts only (see module docstring). anon_token is
        # cleared on claim so a later login by a DIFFERENT account on
        # the same browser can't re-claim someone else's results.
        claimed = 0
        exam_rows = (db.query(ExamSession)
                     .filter(ExamSession.anon_token == anon_id,
                             ExamSession.user_id.is_(None),
                             ExamSession.status != "in_progress")
                     .all())
        for row in exam_rows:
            row.user_id = user.id
            row.anon_token = None
            claimed += 1

        db.commit()
        if newly_linked or journey_rows or claimed:
            audit_log(db, user.id, "identity.anon_linked", {
                "anon_id": anon_id,
                "journey_events_backfilled": int(journey_rows or 0),
                "exam_attempts_claimed": claimed,
            })
    except Exception as e:                            # pragma: no cover
        db.rollback()
        log.warning("identity.link_failed", user_id=user.id,
                    error=str(e))
