# LibyAI — production image
#
# The app defaults to production (fail-closed): a container started
# without WHATSAPP_APP_SECRET will refuse to start, and simulator
# endpoints stay disabled unless ENABLE_PROD_SIMULATOR and a valid
# ADMIN_SECRET_KEY are provided. Pass real secrets only via the
# deployment environment, never by baking them into this image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

# A non-root user, and a writable data directory for the SQLite file.
RUN useradd -m libyai && mkdir -p /app/data && chown -R libyai:libyai /app
USER libyai

EXPOSE 8000

# The container default bind is 0.0.0.0 so the service is reachable from
# outside the container (a localhost bind inside a container answers only
# the container itself). LIBYAI_HOST can still override it; local
# development keeps 127.0.0.1 via app/config.py and .env.example.
CMD ["sh", "-c", "uvicorn app.main:app --host ${LIBYAI_HOST:-0.0.0.0} --port ${LIBYAI_PORT:-8000}"]
