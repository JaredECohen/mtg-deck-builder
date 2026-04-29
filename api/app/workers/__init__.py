"""Worker queue.

Backend-agnostic interface for running long jobs (optimizer runs,
criticality sweeps, profile rebuilds) outside the FastAPI request
lifecycle. The default backend is :class:`ThreadJobQueue` —
in-process, no infra dependencies, suitable for dev and tests. A
:class:`CeleryJobQueue` is provided for production; selecting it via
``MTG_WORKER_BACKEND=celery`` requires Redis at ``REDIS_URL``.

Job results are cached by hash. A repeat optimizer run for the same
constraint envelope is served from cache, free.
"""

from app.workers.queue import (
    Job,
    JobNotFound,
    JobQueue,
    JobStatus,
    ThreadJobQueue,
    get_job_queue,
)
from app.workers.tasks import optimize_deck_task

__all__ = [
    "Job",
    "JobNotFound",
    "JobQueue",
    "JobStatus",
    "ThreadJobQueue",
    "get_job_queue",
    "optimize_deck_task",
]
