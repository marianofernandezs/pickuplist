#!/usr/bin/env sh
set -e

CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-8}"
MAX_TASKS_PER_CHILD="${CELERY_MAX_TASKS_PER_CHILD:-50}"

exec celery -A app.celery_app:celery_app worker \
  --loglevel=INFO \
  --concurrency="$CONCURRENCY" \
  --max-tasks-per-child="$MAX_TASKS_PER_CHILD" \
  --queues=celery
