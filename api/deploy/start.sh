#!/bin/sh
# Container entrypoint (api/Dockerfile): fill or refresh the database on the
# volume, then serve. One worker: caches and the job queue are in-process.
set -e

# The weekly refresh workflow touches this file and restarts the app, so the
# re-ingest runs here, before the server holds ~600 MB of caches.
REFRESH_FLAG=/data/.refresh-cards
if [ -f "$REFRESH_FLAG" ]; then
  rm -f "$REFRESH_FLAG"
  python -m app.scripts.bootstrap_data --refresh-cards
else
  python -m app.scripts.bootstrap_data
fi
# Flush the ingest's writes before warm-up allocates the caches: on a 1 GB
# machine, unflushed database pages plus the caches can trip the OOM killer.
sync

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}" --workers 1
