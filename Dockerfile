# ==============================================================================
# TaskFlow AI - Production Containerfile
# Base: Python 3.12 Slim (Debian)
# Server: Gunicorn with WhiteNoise static assets
# ==============================================================================

FROM python:3.12-slim AS base

# Environment flags for Python runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    APP_HOME=/app

# Install system dependencies (curl for container healthcheck, libpq5 for PostgreSQL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root application user and group
RUN groupadd -r -g 1000 taskflow && \
    useradd -r -u 1000 -g taskflow -d ${APP_HOME} -s /bin/bash taskflow

WORKDIR ${APP_HOME}

# Install Python dependencies separately to cache Docker layers
COPY requirements.txt ${APP_HOME}/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY --chown=taskflow:taskflow . ${APP_HOME}/

# Create staticfiles directory and set permissions
RUN mkdir -p ${APP_HOME}/staticfiles && \
    chown -R taskflow:taskflow ${APP_HOME}/staticfiles

# Run collectstatic at build time using a dummy SECRET_KEY
RUN SECRET_KEY=build-time-dummy-static-collection-key \
    DEBUG=False \
    python manage.py collectstatic --noinput

# Switch to non-root user
USER taskflow

# Expose standard web application port
EXPOSE 8080

# Container healthcheck querying the unauthenticated /health/ endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health/ || exit 1

# Production WSGI server startup
CMD exec gunicorn taskflow_core.wsgi:application --bind 0.0.0.0:${PORT:-8080} --workers 3 --timeout 120 --access-logfile - --error-logfile -

