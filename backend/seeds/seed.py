"""Seed script — run once after `alembic upgrade head`.

Inserts default system_settings, CPMAI topic taxonomy, and creates the
bootstrap super-admin from BOOTSTRAP_ADMIN_* env vars.

TODO: implement after models exist. See engineering spec.
"""
import json
import pathlib

HERE = pathlib.Path(__file__).parent

def main():
    print("Seeding default settings from default_settings.json...")
    defaults = json.loads((HERE / "default_settings.json").read_text())
    print(f"  → {len(defaults)} settings to seed")
    # TODO: open SessionLocal, upsert into SystemSetting
    print("Seeding CPMAI topic taxonomy...")
    # TODO: load topics.json and upsert
    print("Creating bootstrap super-admin...")
    # TODO: read BOOTSTRAP_ADMIN_* and create User if no super_admin exists
    print("Done.")


if __name__ == "__main__":
    main()
