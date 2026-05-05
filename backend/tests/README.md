# Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest -q                                  # all tests
pytest tests/integration/test_exam_lifecycle.py -v
pytest --cov=app --cov-report=term-missing # with coverage
```

Tests use:
- in-memory SQLite (no Postgres needed)
- fakeredis (no Redis needed)
- TestClient (no running uvicorn needed)

So a clean CI run is one `pytest` away.
