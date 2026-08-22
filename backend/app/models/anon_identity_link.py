"""anon_identity_links — permanent browser-identity → account map.

Written once per (anon_id, login): when a visitor who browsed/took
exams anonymously signs in, the login endpoint records "this browser's
anonymous id belongs to user X". Read paths:

  * Contacts traffic widget: classifies a window's visitors — an
    anon_id present here counts as a KNOWN user's visit (from
    ``linked_at`` forward), and the widget's "of which K signed up"
    line counts window anon_ids that appear here at all.
  * Login-time backfill uses the id directly (no read needed) — the
    row is the durable record that the claim happened.

A browser shared by two accounts re-links to the most recent login —
future visits attribute to whoever signed in last; already-backfilled
history keeps its original owner.

Not a guarded table: rows are derived linkage, reconstructible from a
fresh login, and deleted with the user (GDPR).
"""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class AnonIdentityLink(Base):
    __tablename__ = "anon_identity_links"

    id = Column(Integer, primary_key=True)
    # The browser's persistent anonymous id (localStorage
    # cpmai.anon_token, sent as X-Anon-ID). One row per browser.
    anon_id = Column(String(36), nullable=False, unique=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    linked_at = Column(DateTime(timezone=True), server_default=func.now(),
                       nullable=False)
