from typing import Literal
from pydantic import BaseModel, Field


# "paypal" added 2026-05 alongside Razorpay. PayPal handles the non-INR
# rail (different currency routing in PaymentRegistry); Razorpay stays
# on the INR rail.
PaymentProviderType = Literal["razorpay", "paypal", "stripe"]
PaymentMode = Literal["test", "live"]


class PaymentProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider_type: PaymentProviderType = "razorpay"
    mode: PaymentMode = "test"
    display_name: str | None = None
    # `public_key`:
    #   razorpay → key_id
    #   paypal   → Client ID (safe to ship to the browser PayPal SDK)
    public_key: str = Field(min_length=1)
    # `api_secret`:
    #   razorpay → key_secret
    #   paypal   → Client Secret
    # Encrypted on save.
    api_secret: str = Field(min_length=1)
    # `webhook_secret`:
    #   razorpay → webhook signing secret (HMAC)
    #   paypal   → NOT USED (PayPal verifies via cert API); leave null
    # The PayPal `webhook_id` goes in ``config`` instead.
    webhook_secret: str | None = None
    # `config` JSON:
    #   razorpay → {} (no extra config needed)
    #   paypal   → {"webhook_id": "..."}
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
    # Two flags so admin UI can show both rails independently — INR
    # rail is the historical "active" provider; non-INR rail is the
    # new currency-routed one.
    is_active: bool = False                      # true if INR-rail active
    is_non_inr_active: bool = False              # true if non-INR-rail active
    has_api_secret: bool                         # boolean only — never the secret
    has_webhook_secret: bool

    @classmethod
    def from_row(cls, row, is_active: bool = False,
                 is_non_inr_active: bool = False):
        return cls(
            id=row.id, name=row.name, provider_type=row.provider_type,
            mode=row.mode, display_name=row.display_name,
            public_key=row.public_key, config=row.config or {},
            is_enabled=row.is_enabled, priority=row.priority,
            is_active=is_active,
            is_non_inr_active=is_non_inr_active,
            has_api_secret=row.api_secret_encrypted is not None,
            has_webhook_secret=row.webhook_secret_encrypted is not None,
        )
