import enum
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Enum as SQLEnum
from sqlalchemy.sql import func
from app.core.database import Base


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class User(Base):
    __tablename__ = "users"
    id                 = Column(Integer, primary_key=True)
    email              = Column(String(255), unique=True, nullable=False, index=True)
    # Nullable: Google-only accounts have no password. Admins can still set
    # one to keep password login as a fallback alongside Google.
    password_hash      = Column(String(255), nullable=True)
    # Google OIDC subject (`sub` claim). Unique per Google account; nullable
    # so password-only users have no Google linkage.
    google_id          = Column(String(64), unique=True, nullable=True, index=True)
    name               = Column(String(120))
    role               = Column(SQLEnum(UserRole, name="user_role"),
                                default=UserRole.USER, nullable=False, index=True)
    is_active          = Column(Boolean, default=True, nullable=False)
    # Per-user chat daily-limit override. NULL → use the global setting
    # `chat.daily_limit.authenticated`. Set to give a specific user a
    # higher (or lower) cap without changing the global default. Admin
    # edits via the user-admin UI.
    daily_chat_limit_override = Column(Integer, nullable=True)
    failed_login_count = Column(Integer, default=0, nullable=False)
    locked_until       = Column(DateTime(timezone=True))
    last_login_at      = Column(DateTime(timezone=True))
    # GeoIP enrichment (migration 0019). Both populated at signup time
    # AND refreshed on each login. Snapshot semantics: ``country`` /
    # ``city`` are "where the account was created"; ``last_login_*`` are
    # the most-recent-login snapshot. The pair gives the admin analytics
    # dashboard two independent slices: "signups by country" (cohorts)
    # and "currently-active users by country" (engagement). Nullable for
    # historical users + private-IP / lookup-miss / failed-geoip cases.
    country               = Column(String(2))     # ISO-3166-1 alpha-2
    city                  = Column(String(120))
    last_login_ip         = Column(String(45))    # IPv6 max 39 + headroom
    last_login_country    = Column(String(2))
    # GDPR soft-delete marker. Set by `DELETE /users/me`; once non-NULL,
    # the user cannot log in and PII has been redacted (email rewritten
    # to deleted-{id}@redacted.invalid, name/password_hash/google_id
    # NULL). Financial rows (payments, subscriptions) are retained for
    # tax-law compliance.
    deleted_at         = Column(DateTime(timezone=True), nullable=True)
    # Admin-only free-text notes, surfaced + editable in the Contacts feed
    # (/admin/leads). Parallels ``Lead.notes`` so operators can jot
    # follow-up details on signed-up users too. Never shown to the user.
    notes              = Column(Text)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())
    updated_at         = Column(DateTime(timezone=True),
                                server_default=func.now(), onupdate=func.now())
