from datetime import date, datetime
from pydantic import BaseModel, EmailStr, Field
from app.models.user import UserRole


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    name: str | None = Field(default=None, max_length=120)
    consent_marketing: bool = False
    target_exam_date: date | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginIn(BaseModel):
    """Body for POST /auth/google.

    `credential` is the JWT Google Sign-In gives the frontend in its
    callback. The backend verifies it against the configured Google
    OAuth client ID and finds-or-creates the user.
    """
    credential: str


class RefreshIn(BaseModel):
    refresh_token: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


class UserOut(BaseModel):
    id: int
    # Output schema uses plain ``str``, NOT ``EmailStr``. After GDPR
    # soft-delete the email is rewritten to ``deleted-{id}@redacted.invalid``
    # — a RFC 2606 reserved domain that Pydantic's EmailStr rejects.
    # Validation belongs at INPUT time (SignupIn, LoginIn — both use
    # EmailStr). Once the value is stored, serialization should
    # round-trip cleanly without re-validating against the strict
    # email_validator rules. This caught a 500 from GET /admin/users/{id}
    # on soft-deleted users.
    email: str
    name: str | None
    role: UserRole
    created_at: datetime
    # GeoIP-resolved signup country (ISO-3166-1 alpha-2). Surfaced on
    # the user-facing UserOut so /pricing can default the currency
    # picker (IN → INR; other → USD by default). Nullable for users
    # who pre-date the GeoIP feature or whose IP resolved to a
    # private/unknown range. PII-fine to expose to the user themselves
    # (it's their own country); admins see this same field via
    # UserAdminOut.
    country: str | None = None

    class Config:
        from_attributes = True


class UserAdminOut(UserOut):
    is_active: bool
    failed_login_count: int
    locked_until: datetime | None
    last_login_at: datetime | None
    # Set when the user has gone through the GDPR / admin soft-delete
    # flow. After this is non-null: email is "deleted-{id}@redacted.invalid",
    # name/password_hash/google_id are NULL, is_active=False. The admin
    # UI dims these rows and labels them "deleted" so operators don't
    # confuse them with active accounts.
    deleted_at: datetime | None = None
    # GeoIP enrichment (PR-A). ``country`` / ``city`` are signup-time
    # snapshots; ``last_login_country`` / ``last_login_ip`` are the
    # most-recent-login snapshot. All nullable for historical rows
    # and lookup-miss / private-IP cases.
    country: str | None = None
    city: str | None = None
    last_login_ip: str | None = None
    last_login_country: str | None = None
    # Login-method & subscription summaries — populated by the endpoint.
    has_google: bool = False
    has_password: bool = False
    has_active_subscription: bool = False
    subscription_plan: str | None = None
    # NULL = falls back to global chat.daily_limit.authenticated setting.
    # Admin sets via PATCH /admin/users/{id}/chat-limit.
    daily_chat_limit_override: int | None = None
    # Contact details the user left on a landing lead (matched by email),
    # surfaced read-only so an admin sees how to reach them. Nullable when
    # there's no matching lead / the field wasn't provided. Existing WhatsApp
    # numbers are preserved and surfaced here (country_code + number).
    linkedin_id: str | None = None
    whatsapp: str | None = None


class SubscriptionSummary(BaseModel):
    active: bool
    plan: str | None = None
    status: str | None = None
    current_period_end: datetime | None = None


class UserDashboardOut(BaseModel):
    """Self-view returned by /users/me/dashboard. Includes subscription
    so the learner UI can decide what's accessible / what to upsell."""
    user: UserOut
    subscription: SubscriptionSummary
    has_google: bool
    has_password: bool


class AuthTokens(BaseModel):
    access: str
    refresh: str
    user: UserOut


class RefreshOut(BaseModel):
    access: str
    refresh: str
