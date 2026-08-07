"""SQLAlchemy session factory + declarative Base."""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings

# Pool sized for concurrent exam traffic: SQLAlchemy's defaults (5+10)
# capped the whole app at 15 simultaneous DB operations — burst moments
# (a cohort starting a mock exam together, dashboards firing parallel
# queries) queued behind them (perf review 2026-08-07). 10+20 = 30 max,
# still well under Postgres's default max_connections=100 even with two
# uvicorn workers (2×30 + a few for psql/backup). Postgres-only: the
# test suite's SQLite SingletonThreadPool rejects these kwargs.
_pool_kwargs = ({"pool_size": 10, "max_overflow": 20}
                if settings.DATABASE_URL.startswith("postgresql") else {})
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True,
                       **_pool_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()
