from typing import Literal
from pydantic import BaseModel, Field


PaymentProviderType = Literal["razorpay", "stripe"]
PaymentMode = Literal["test", "live"]


class PaymentProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider_type: PaymentProviderType = "razorpay"
    mode: PaymentMode = "test"
    display_name: str | None = None
    public_key: str = Field(min_length=1)        # razorpay key_id
    api_secret: str = Field(min_length=1)        # razorpay key_secret — encrypted on save
    webhook_secret: str | None = None            # encrypted on save
    config: dict | None = None
    is_enabled: bool = True
    priority: int = 100


class PaymentProviderUpdate(BaseModel):
    name: str | None = None
    mode: PaymentMode | None = None
    display_name: str | None = None
    public_key: str | None = None
    api_secret: str | None = None                # send to rotate; omit to keep
    webhook_secret: str | None = None
    config: dict | None = None
    is_enabled: bool | None = None
    priority: int | None = None


class PaymentProviderOut(BaseModel):
    id: int
    name: str
    provider_type: str
    mode: str
    display_name: str | None
    public_key: str | None                       # safe to expose (publishable)
    config: dict
    is_enabled: bool
    priority: int
    is_active: bool = False
    has_api_secret: bool                         # boolean only — never the secret
    has_webhook_secret: bool

    @classmethod
    def from_row(cls, row, is_active: bool = False):
        return cls(
            id=row.id, name=row.name, provider_type=row.provider_type,
            mode=row.mode, display_name=row.display_name,
            public_key=row.public_key, config=row.config or {},
            is_enabled=row.is_enabled, priority=row.priority,
            is_active=is_active,
            has_api_secret=row.api_secret_encrypted is not None,
            has_webhook_secret=row.webhook_secret_encrypted is not None,
        )
