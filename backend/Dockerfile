FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.12-slim AS runtime
RUN groupadd -r app && useradd -r -g app app && \
    apt-get update && apt-get install -y --no-install-recommends tini && \
    rm -rf /var/lib/apt/lists/*
COPY --from=builder /root/.local /home/app/.local
WORKDIR /app
COPY --chown=app:app . .
# Pre-create the uploads mount point with app ownership BEFORE the named
# volume gets mounted on top. Docker initializes a fresh named volume
# from the image's contents at the mount path — so if /app/uploads
# exists here owned by app:app, the volume inherits that ownership.
# Without this, Docker's volume driver creates /app/uploads as root:root
# on first mount and the app user (UID 999) can't write subdirectories
# like /app/uploads/{tenant}/{YYYY}/{MM}/ at request time — every
# upload would fail with EACCES. The directory itself is empty in the
# image; runtime content lives in the cpmai-uploads named volume.
# See docker-compose.yml and backend/app/api/v1/endpoints/admin/uploads.py.
RUN mkdir -p /app/uploads && chown app:app /app/uploads
USER app
ENV PATH=/home/app/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
