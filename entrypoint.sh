#!/bin/sh
set -e

# The media directory is a host volume. Docker creates it as root, while the
# app runs as uid 1001. Fix ownership before dropping privileges, or image
# uploads fail with PermissionError and Django returns 500.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/media /app/staticfiles
  chown -R django:django /app/media /app/staticfiles
  exec gosu django "$0" "$@"
fi

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
