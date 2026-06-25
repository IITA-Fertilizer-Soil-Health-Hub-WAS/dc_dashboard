# Multi-stage build for the Django app.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY . .

RUN python manage.py collectstatic --noinput --settings=eia_dcmt.settings.prod || true

EXPOSE 8000

CMD ["gunicorn", "eia_dcmt.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--worker-class", "gthread", "--workers", "2", "--threads", "4", \
     "--timeout", "120", "--worker-tmp-dir", "/dev/shm", "--graceful-timeout", "30"]
