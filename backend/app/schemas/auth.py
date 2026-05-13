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
    email: EmailStr
    name: str | None
    role: UserRole
    created_at: datetime

    class Config:
        from_attributes = True


class UserAdminOut(UserOut):
    is_active: bool
    failed_login_count: int
    locked_until: datetime | None
    last_login_at: datetime | None
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
