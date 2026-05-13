from datetime import datetime
from typing import Any
from pydantic import BaseModel


class SettingOut(BaseModel):
    key: str
    value: Any
    description: str | None = None
    updated_at: datetime | None = None
    # ``is_secret`` is included so the frontend can render a masked
    # input (write-only) instead of a plain text field. The ``value``
    # field for secret rows is the masked representation (e.g.
    # ``"••••6e4f"``), never the plaintext — see endpoint logic.
    is_secret: bool = False

    class Config:
        from_attributes = True


class SettingUpdate(BaseModel):
    value: Any
