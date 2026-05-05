from datetime import datetime
from typing import Any
from pydantic import BaseModel


class SettingOut(BaseModel):
    key: str
    value: Any
    description: str | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class SettingUpdate(BaseModel):
    value: Any
