"""Generate a tiny GeoLite2-City-shaped .mmdb file for testing.

Run from ``backend/``:

    pip install mmdb_writer netaddr
    python -m tests.unit.geoip.fixtures.build_fixture

Idempotent — overwrites the existing fixture file.

The three records cover the cases our unit tests care about:

  * 1.1.1.1        → IN / Bengaluru   (happy path, IPv4)
  * 2606:4700::1   → SG / Singapore   (happy path, IPv6)
  * 8.8.8.8        → AE / —           (country only, no city)

These IPs are publicly routable in the real world (Cloudflare 1.1.1.1,
Cloudflare IPv6 2606:4700::/32, Google 8.8.8.8). We override their
country/city in the fixture for test purposes — the real-world
ownership is irrelevant for the lookup mechanic we're testing.

We chose them over the RFC 5737/3849 "documentation" ranges because as
of Python 3.12, those ranges are now classified by ``ipaddress.ip_address``
as ``is_private=True``. The lookup module short-circuits private IPs
without consulting the DB — that's the correct production behavior,
but it means doc-range IPs can't be tested end-to-end. Public IPs avoid
that filter while still being deterministic test inputs.
"""
from __future__ import annotations
import pathlib

try:
    # mmdb_writer + netaddr are dev-only dependencies for fixture
    # generation. Imported inside the function so the package can be
    # imported by other modules even when these aren't installed.
    from mmdb_writer import MMDBWriter
    from netaddr import IPSet
except ImportError:  # pragma: no cover
    raise SystemExit(
        "mmdb_writer / netaddr not installed. Run:\n"
        "    pip install mmdb_writer netaddr\n"
        "then re-run this build script.")


OUTPUT = pathlib.Path(__file__).parent / "test-City.mmdb"


RECORDS = [
    {
        "network": "1.1.1.1/32",
        "data": {
            "country": {"iso_code": "IN", "names": {"en": "India"}},
            "city": {"names": {"en": "Bengaluru"}},
            "location": {"latitude": 12.97, "longitude": 77.59},
        },
    },
    {
        "network": "2606:4700::1/128",
        "data": {
            "country": {"iso_code": "SG", "names": {"en": "Singapore"}},
            "city": {"names": {"en": "Singapore"}},
            "location": {"latitude": 1.29, "longitude": 103.85},
        },
    },
    {
        "network": "8.8.8.8/32",
        "data": {
            "country": {"iso_code": "AE", "names": {"en": "United Arab Emirates"}},
            "location": {"latitude": 25.20, "longitude": 55.27},
        },
    },
]


def main() -> None:
    writer = MMDBWriter(
        ip_version=6,
        ipv4_compatible=True,
        database_type="GeoLite2-City",
        languages=["en"],
        description={"en": "cpmai test fixture (synthetic)"},
    )
    for record in RECORDS:
        # mmdb_writer's insert_network takes a netaddr.IPSet, not a
        # CIDR string. IPSet([cidr]) is a single-network set.
        writer.insert_network(IPSet([record["network"]]), record["data"])
    writer.to_db_file(str(OUTPUT))
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
