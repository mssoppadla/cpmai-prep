"""Runtime settings — read-through Redis cache over the system_settings table.

Reads are O(1) from Redis. Writes go to Postgres, then publish on a Redis
channel so other workers invalidate immediately.
"""
import json
import threading
import time
from typing import Any
from sqlalchemy.orm import Session
from app.core.redis import redis_client
from app.core.database import SessionLocal
from app.models.system_setting import SystemSetting

CACHE_PREFIX  = "setting:"
INVAL_CHANNEL = "settings:invalidate"
DEFAULT_TTL   = 30

_local: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


class SettingsStore:
    def __init__(self, ttl: int = DEFAULT_TTL):
        self.ttl = ttl

    def get(self, key: str, default: Any = None) -> Any:
        cached = _local.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        raw = redis_client.get(CACHE_PREFIX + key)
        if raw is not None:
            value = json.loads(raw)
            _local[key] = (time.monotonic() + self.ttl, value)
            return value
        with SessionLocal() as db:
            row = db.get(SystemSetting, key)
        value = row.value if row else default
        try:
            redis_client.setex(CACHE_PREFIX + key, self.ttl, json.dumps(value))
        except Exception:
            pass
        _local[key] = (time.monotonic() + self.ttl, value)
        return value

    def get_int(self, key: str, default: int = 0) -> int:
        v = self.get(key, default)
        try:
            return int(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        v = self.get(key, default)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    def get_str(self, key: str, default: str = "") -> str:
        v = self.get(key, default)
        return str(v) if v is not None else default

    def set(self, key: str, value: Any, *, db: Session, updated_by: int) -> None:
        row = db.get(SystemSetting, key)
        if row:
            row.value = value
            row.updated_by = updated_by
        else:
            db.add(SystemSetting(key=key, value=value, updated_by=updated_by))
        db.commit()
        try:
            redis_client.delete(CACHE_PREFIX + key)
            redis_client.publish(INVAL_CHANNEL, key)
        except Exception:
            pass
        with _lock:
            _local.pop(key, None)

    def all(self, db: Session) -> list[SystemSetting]:
        return db.query(SystemSetting).order_by(SystemSetting.key).all()


settings_store = SettingsStore()


def start_invalidation_listener():
    import structlog
    log = structlog.get_logger("settings_store")
    pubsub = redis_client.pubsub()
    pubsub.subscribe(INVAL_CHANNEL)
    for msg in pubsub.listen():
        if msg.get("type") != "message":
            continue
        key = msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"]
        with _lock:
            _local.pop(key, None)
        log.debug("settings.local_cache_invalidated", key=key)
