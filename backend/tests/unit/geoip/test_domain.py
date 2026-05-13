"""Domain-type sanity checks. Quick wins, prevent regressions like
'the GeoLocation dataclass lost its frozen=True and started getting
mutated downstream'."""
from app.services.geoip.domain import (
    GeoLocation, StatusReport, RefreshResult,
    GeoIPError, CredentialsError, DatabaseError, NetworkError,
)


def test_geolocation_is_frozen():
    """We rely on GeoLocation being hashable / safe-to-cache. Frozen
    dataclasses give us both for free."""
    geo = GeoLocation(country="IN", city="Bengaluru")
    try:
        geo.country = "SG"  # type: ignore[misc]
    except Exception:
        return  # FrozenInstanceError
    raise AssertionError("GeoLocation should be frozen (immutable).")


def test_geolocation_supports_partial_fields():
    """A country-only record (e.g. anonymous proxy) must be representable."""
    geo = GeoLocation(country="AE")
    assert geo.country == "AE"
    assert geo.city is None
    assert geo.latitude is None


def test_status_report_defaults_are_safe():
    """A default-constructed StatusReport must read as 'no DB present'.
    The /health endpoint relies on this when the geoip package can't
    even be imported."""
    report = StatusReport()
    assert report.database_present is False
    assert report.database_stale is False
    assert report.credentials_configured is False


def test_refresh_result_not_modified_is_a_success_shape():
    """When MaxMind returns 304, we return updated=False but it's still
    a success — message should NOT contain error-flavored text."""
    result = RefreshResult(updated=False, message="No update available.")
    assert result.updated is False
    assert "fail" not in result.message.lower()
    assert "error" not in result.message.lower()


def test_error_hierarchy_inherits_from_geoip_error():
    """Callers ``except GeoIPError`` to catch any refresh failure mode.
    If a new error class forgets to inherit, that broad-except misses it."""
    assert issubclass(CredentialsError, GeoIPError)
    assert issubclass(DatabaseError, GeoIPError)
    assert issubclass(NetworkError, GeoIPError)
