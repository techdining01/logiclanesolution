FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=core.settings_production

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# collectstatic needs the required env vars — pass dummy values at build time
# only; real secrets are injected at runtime by the platform.
RUN SECRET_KEY=build-only \
    ALLOWED_HOSTS=localhost \
    DATABASE_URL=sqlite:////tmp/build.db \
    PAYVESSEL_API_KEY=build \
    PAYVESSEL_SECRET_KEY=build \
    PAYVESSEL_BUSINESS_ID=build \
    EMAIL_HOST_USER=build@build.com \
    EMAIL_HOST_PASSWORD=build \
    python manage.py collectstatic --noinput

EXPOSE 8000

CMD gunicorn core.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers 3 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
