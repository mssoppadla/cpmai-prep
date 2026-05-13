"""cpmai-specific adapter: ``SettingsProvider`` over ``settings_store``.

This is the ONLY file in the geoip package that imports from
``app.core``. Everything else takes a ``SettingsProvider`` instance.
When extracting this package to its own service, replace this file (or
write a sibling) with an implementation backed by env vars, a config
file, or an HTTP endpoint — no other geoip module needs to change.

Security notes
--------------
* The license key is stored in the ``system_settings`` table with
  ``is_secret=True``. The /admin/settings GET endpoint masks the value
  for transport; PATCH accepts plaintext.
* ``__repr__`` is overridden to avoid printing secret values into
  structured logs if a developer logs the provider instance.
* The adapter never calls ``log.info(license_key)`` or similar. Refresh
  errors include WHICH key failed but NOT its value.
"""
from __future__ import annotations
from typing import Optional

from app.core.settings_store import settings_store
from app.services.geoip.protocols import SettingsKeys


# Keys that contain secret values. Mirrored in /admin/settings response
# masking; defined here too so that "what is a secret" lives next to
# the keys themselves rather than in a far-away endpoint file.
SECRET_KEYS = frozenset({SettingsKeys.MAXMIND_LICENSE_KEY})


class CpmaiSettingsProvider:
    """Wraps the global ``settings_store`` to match the SettingsProvider
    Protocol. Stateless; safe to instantiate per-call or reuse a single
    module-level instance.

    The Optional[str] return type narrows ``settings_store.get()``'s
    ``Any`` return: this package only stores str / int / bool, and the
    protocol pins the contract so misuse is caught early.
    """

    def get(self, key: str) -> Optional[str]:
        value = settings_store.get(key)
        if value is None or value == "":
            return None
        return str(value)

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = settings_store.get(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        # Settings table stores JSON; "true"/"false" string from CLI
        # writes should also work. Be defensive.
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)

    def get_int(self, key: str, default: int = 0) -> int:
        return settings_store.get_int(key, default)

    def __repr__(self) -> str:
        # Defensive: don't reveal even the presence of values. A
        # __repr__ that says "key=Wfpm…" would be a log-leak waiting
        # to happen.
        return "<CpmaiSettingsProvider>"


# Module-level singleton — callers typically use this rather than
# instantiating their own. Tests can inject a different provider.
default_provider = CpmaiSettingsProvider()
