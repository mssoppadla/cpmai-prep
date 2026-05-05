"""Shared rate-limiter instance.

Lives outside app.main to avoid circular imports — endpoints need the
limiter at import time, but main.py also imports endpoints.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.config import settings

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)
