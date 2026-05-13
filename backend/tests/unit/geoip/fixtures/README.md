# GeoIP test fixtures

This directory holds a minimal `.mmdb` file used by the geoip lookup
tests. The file is generated, not hand-edited.

## Why not commit a binary?

A "real" MaxMind file is 30+ MB and license-restricted (GeoLite2 has
attribution requirements). For tests we only need a few records: one
known-good city, one known-good country-only, one unknown. We generate
that synthetic mmdb at fixture-build time using `maxminddb-writer`.

## Generating

When/if we want a fixture, run from `backend/`:

```bash
pip install maxminddb-writer==0.2.1
python -m tests.unit.geoip.fixtures.build_fixture
```

The build script writes `test-City.mmdb` next to this README with
these records:

| IP | Country | City | Notes |
|---|---|---|---|
| `203.0.113.1` | `IN` | `Bengaluru` | Happy path |
| `2001:db8::1` | `SG` | `Singapore` | IPv6 happy path |
| `198.51.100.1` | `AE` | — | Country-only, no city |

The IPs are from RFC 5737 / RFC 3849 documentation ranges — guaranteed
never to clash with real prod data.

## Without the fixture

Tests that need the mmdb gracefully **skip** rather than fail (see
`conftest.py::synthetic_mmdb_path`). The non-lookup unit tests
(domain, refresh-with-mocked-httpx, settings adapter, CLI argument
parsing) don't need the fixture and run unconditionally.
