#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -o errexit

# Install project dependencies
pip install -r requirements.txt

# Collect static files with WhiteNoise
python manage.py collectstatic --noinput

# Apply database migrations to the target database
python manage.py migrate

