#!/bin/sh
set -e
echo "Waiting for PostgreSQL..."
while ! python -c "import os, psycopg; psycopg.connect(os.environ['DATABASE_URL'])" 2>/dev/null; do
  echo "Postgres is unavailable - sleeping"
  sleep 2
done
echo "Running migrations..."
python manage.py migrate --noinput
echo "Collecting static files..."
python manage.py collectstatic --noinput
echo "Starting Gunicorn..."
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 1 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
