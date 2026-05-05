"""Application exceptions — handled by api/exception_handlers.py."""
from fastapi import HTTPException, status


class AppError(HTTPException):
    code: str = "app_error"
    def __init__(self, message: str, *, status_code: int = 400, **fields):
        super().__init__(status_code=status_code, detail={
            "code": self.code, "message": message, **fields,
        })


class InvalidCredentialsError(AppError):
    code = "invalid_credentials"
    def __init__(self):
        super().__init__("Invalid email or password.", status_code=status.HTTP_401_UNAUTHORIZED)


class AccountLockedError(AppError):
    code = "account_locked"
    def __init__(self, locked_until):
        super().__init__("Account temporarily locked.",
                         status_code=status.HTTP_423_LOCKED,
                         locked_until=str(locked_until))


class UnauthorizedError(AppError):
    code = "unauthorized"
    def __init__(self, message: str = "Authentication required"):
        super().__init__(message, status_code=status.HTTP_401_UNAUTHORIZED)


class ForbiddenError(AppError):
    code = "forbidden"
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message, status_code=status.HTTP_403_FORBIDDEN)


class NotFoundError(AppError):
    code = "not_found"
    def __init__(self, message: str = "Not found"):
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND)


class ConflictError(AppError):
    code = "conflict"
    def __init__(self, message: str):
        super().__init__(message, status_code=status.HTTP_409_CONFLICT)


class ValidationError(AppError):
    code = "validation_failed"
    def __init__(self, message: str, fields: dict | None = None):
        super().__init__(message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                         fields=fields or {})


class SubscriptionRequiredError(AppError):
    code = "subscription_required"
    def __init__(self):
        super().__init__("Active subscription required",
                         status_code=status.HTTP_402_PAYMENT_REQUIRED)


class ChatLimitReached(AppError):
    code = "chat_daily_limit_reached"
    def __init__(self, limit: int, reset_at_utc: str):
        super().__init__(f"Daily limit of {limit} messages reached.",
                         status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                         limit=limit, reset_at_utc=reset_at_utc)


class GuardrailViolation(AppError):
    code = "guardrail_violation"
    def __init__(self, code: str, message: str, **meta):
        self.code = code
        super().__init__(message, status_code=status.HTTP_400_BAD_REQUEST, **meta)
