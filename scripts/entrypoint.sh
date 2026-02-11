#!/usr/bin/env bash
set -e

MANAGE="python manage.py"

echo "Running migrations..."
$MANAGE migrate --no-input

echo "Collecting static files..."
$MANAGE collectstatic --no-input

exec python manage.py runserver 0.0.0.0:8000

