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


class AuthTokens(BaseModel):
    access: str
    refresh: str
    user: UserOut


class RefreshOut(BaseModel):
    access: str
    refresh: str
