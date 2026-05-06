import enum
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum as SQLEnum
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
    failed_login_count = Column(Integer, default=0, nullable=False)
    locked_until       = Column(DateTime(timezone=True))
    last_login_at      = Column(DateTime(timezone=True))
    created_at         = Column(DateTime(timezone=True), server_default=func.now())
    updated_at         = Column(DateTime(timezone=True),
                                server_default=func.now(), onupdate=func.now())
