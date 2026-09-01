#!/bin/sh
set -e
echo "Waiting for PostgreSQL database..."
while ! python -c "
import os, psycopg
try:
    psycopg.connect(os.environ.get('DATABASE_URL'))
    print('Database connected successfully.')
except Exception as e:
    exit(1)
" 2>/dev/null; do
    echo "Postgres is unavailable - sleeping 2 seconds"
    sleep 2
done
echo "Running database migrations..."
python manage.py migrate --noinput
echo "Collecting static files..."
python manage.py collectstatic --noinput --clear
echo "Starting Gunicorn server on 0.0.0.0:8000..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
