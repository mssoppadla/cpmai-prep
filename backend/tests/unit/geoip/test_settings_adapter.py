"""Verify the cpmai SettingsProvider adapter.

We don't unit-test ``settings_store`` here (that has its own suite) —
we test that ``CpmaiSettingsProvider`` correctly translates the underlying
store's quirks into the geoip Protocol shape:

  * Empty-string is normalized to None on .get() — so `if provider.get(k)`
    works as a "is it set?" check without callers worrying about ""
  * __repr__ is opaque — must NOT include any stored values
  * Bool coercion handles string "true"/"false" forms (which the
    /admin/settings PATCH-from-text-field path produces)

We mock ``settings_store`` to avoid bringing up Postgres/Redis.
"""
from __future__ import annotations
from unittest.mock import patch

from app.services.geoip.protocols import SettingsKeys, SettingsProvider
from app.services.geoip.settings import (
    CpmaiSettingsProvider, SECRET_KEYS, default_provider,
)


def test_provider_implements_protocol():
    """The adapter must structurally satisfy SettingsProvider."""
    assert isinstance(CpmaiSettingsProvider(), SettingsProvider)


def test_get_returns_none_for_empty_string():
    """`settings_store` stores empty strings for "unset" string-typed
    keys. The adapter normalizes these to None so callers can
    `if provider.get(...)` as the "is it configured?" check."""
    provider = CpmaiSettingsProvider()
    with patch("app.services.geoip.settings.settings_store.get",
               return_value=""):
        assert provider.get("anything") is None


def test_get_returns_none_for_actual_none():
    provider = CpmaiSettingsProvider()
    with patch("app.services.geoip.settings.settings_store.get",
               return_value=None):
        assert provider.get("anything") is None


def test_get_returns_string_value():
    provider = CpmaiSettingsProvider()
    with patch("app.services.geoip.settings.settings_store.get",
               return_value="hello"):
        assert provider.get("anything") == "hello"


def test_get_coerces_int_to_string():
    """Account IDs may be stored as JSON numbers; consumers expect strings."""
    provider = CpmaiSettingsProvider()
    with patch("app.services.geoip.settings.settings_store.get",
               return_value=1345788):
        assert provider.get("anything") == "1345788"


def test_get_bool_default_when_unset():
    provider = CpmaiSettingsProvider()
    with patch("app.services.geoip.settings.settings_store.get",
               return_value=None):
        assert provider.get_bool("anything") is False
        assert provider.get_bool("anything", default=True) is True


def test_get_bool_with_native_bool():
    provider = CpmaiSettingsProvider()
    with patch("app.services.geoip.settings.settings_store.get",
               return_value=True):
        assert provider.get_bool("anything") is True
    with patch("app.services.geoip.settings.settings_store.get",
               return_value=False):
        assert provider.get_bool("anything") is False


def test_get_bool_with_truthy_strings():
    """Some admin UIs PATCH bool-typed settings as strings."""
    provider = CpmaiSettingsProvider()
    for truthy in ("true", "True", "TRUE", "1", "yes", "on"):
        with patch("app.services.geoip.settings.settings_store.get",
                   return_value=truthy):
            assert provider.get_bool("k") is True, (
                f"{truthy!r} should be truthy")
    for falsy in ("false", "False", "no", "off", "0"):
        with patch("app.services.geoip.settings.settings_store.get",
                   return_value=falsy):
            assert provider.get_bool("k") is False, (
                f"{falsy!r} should be falsy")


def test_get_int_passes_through_to_store():
    """The store has its own get_int helper; we should be using it."""
    provider = CpmaiSettingsProvider()
    with patch("app.services.geoip.settings.settings_store.get_int",
               return_value=42) as m:
        assert provider.get_int("anything", default=99) == 42
        m.assert_called_once_with("anything", 99)


def test_repr_does_not_leak_anything():
    """A debug print or log message that includes ``provider`` must
    NOT reveal values. The whole point of __repr__ override is to make
    `log.info("ctx=%s", provider)` boring."""
    out = repr(CpmaiSettingsProvider())
    assert "Wfpm" not in out  # in case some test accidentally seeds this
    assert "license" not in out.lower()
    assert "key" not in out.lower()
    # Just a tag — opaque.
    assert "CpmaiSettingsProvider" in out


def test_default_provider_is_singleton_shape():
    """The module-level singleton is just a convenience — must be an
    instance of CpmaiSettingsProvider, not a different class entirely."""
    assert isinstance(default_provider, CpmaiSettingsProvider)


def test_secret_keys_includes_license_key():
    """If someone removes the license key from SECRET_KEYS, the
    /admin/settings GET would start echoing plaintext. Pin it."""
    assert SettingsKeys.MAXMIND_LICENSE_KEY in SECRET_KEYS
