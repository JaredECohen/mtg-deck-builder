"""Celery-backed JobQueue.

Lazily imported by ``get_job_queue()`` only when
``MTG_WORKER_BACKEND=celery``. Requires:

* ``REDIS_URL`` — broker (default ``redis://localhost:6379/0``)
* ``MTG_CELERY_RESULT_BACKEND`` — optional, defaults to the same Redis URL
* ``celery`` package installed (``pip install celery[redis]``)

The Celery app is module-global so ``celery -A app.workers.celery_backend
worker`` picks it up. Tests don't import this module — they use
``ThreadJobQueue``.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Callable, Iterable

from app.workers.queue import Job, JobNotFound, JobQueue


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _make_celery_app():
    """Build the global Celery app. Cached at module level."""
    from celery import Celery  # lazy

    broker = _redis_url()
    backend = os.getenv("MTG_CELERY_RESULT_BACKEND", broker)
    app = Celery(
        "mtg_deck_builder",
        broker=broker,
        backend=backend,
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        result_expires=24 * 60 * 60,
    )
    return app


# Cached at module load — both the API process and workers import this.
celery_app = None  # set on first use to keep import-time light


def _get_app():
    global celery_app
    if celery_app is None:
        celery_app = _make_celery_app()
        _register_tasks(celery_app)
    return celery_app


_registered = False
_register_lock = threading.Lock()


def _register_tasks(app) -> None:
    """Register the dispatch task. Workers and the API process must
    register the same task signatures."""
    global _registered
    with _register_lock:
        if _registered:
            return

        @app.task(name="mtg.dispatch", bind=True)
        def _dispatch(self, fn_module: str, fn_name: str, args_json: str, kwargs_json: str):
            """Generic dispatcher: imports ``fn_module.fn_name`` and calls it.

            We cannot pickle arbitrary callables across processes — so the
            dispatcher takes a module + function name, deserializes args
            from JSON, and calls the function. This forces task functions
            to accept JSON-serializable arguments only.
            """
            import importlib
            module = importlib.import_module(fn_module)
            fn = getattr(module, fn_name)
            args = json.loads(args_json)
            kwargs = json.loads(kwargs_json)
            return fn(*args, **kwargs)

        app._mtg_dispatch = _dispatch  # type: ignore[attr-defined]
        _registered = True


class CeleryJobQueue(JobQueue):
    """Production queue backed by Celery + Redis.

    Cache lookups are also Redis-backed via a separate hash so cache
    hits don't require a Celery roundtrip. Job state is read directly
    from Celery's result backend.
    """

    def __init__(self):
        self._app = _get_app()
        self._lock = threading.RLock()
        # Local in-process cache of (job_id -> Job) for status reads
        # so the API process doesn't hit Redis on every poll.
        self._jobs: dict[str, Job] = {}
        # Result cache (cache_key -> result) backed by Redis.
        try:
            import redis  # type: ignore
            self._redis = redis.Redis.from_url(_redis_url(), decode_responses=True)
        except Exception:
            self._redis = None

    def submit(
        self,
        name: str,
        fn: Callable[..., Any],
        *,
        args: Iterable[Any] = (),
        kwargs: dict[str, Any] | None = None,
        cache_key: str | None = None,
    ) -> Job:
        kwargs = dict(kwargs or {})
        # Cache hit?
        if cache_key and self._redis is not None:
            cached = self._redis.hget("mtg:results", cache_key)
            if cached is not None:
                job = Job(
                    id=str(uuid.uuid4()),
                    name=name,
                    status="cached",
                    started_at=time.time(),
                    finished_at=time.time(),
                    result=json.loads(cached),
                    cache_key=cache_key,
                )
                with self._lock:
                    self._jobs[job.id] = job
                return job

        fn_module = getattr(fn, "__module__", "")
        fn_name = getattr(fn, "__name__", "")
        if not fn_module or not fn_name:
            raise ValueError(f"Cannot dispatch {fn!r} — no module/name attributes")

        # Drop ``_job_progress`` if present — Celery doesn't share
        # in-memory state across processes; progress tracking is via the
        # result backend instead.
        kwargs.pop("_job_progress", None)

        try:
            args_json = json.dumps(list(args), default=_serialize_arg)
            kwargs_json = json.dumps(kwargs, default=_serialize_arg)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Cannot serialize task args to JSON: {exc}") from exc

        async_result = self._app._mtg_dispatch.apply_async(  # type: ignore[attr-defined]
            args=(fn_module, fn_name, args_json, kwargs_json),
        )
        job = Job(id=async_result.id, name=name, status="pending", cache_key=cache_key)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        async_result = self._app.AsyncResult(job_id)
        state = async_result.state  # PENDING / STARTED / SUCCESS / FAILURE / RETRY
        if job is None:
            if state == "PENDING":
                raise JobNotFound(job_id)
            job = Job(id=job_id, name="<unknown>", status="pending")
            with self._lock:
                self._jobs[job_id] = job

        if state == "PENDING":
            job.status = "pending"
        elif state == "STARTED":
            job.status = "running"
            if job.started_at is None:
                job.started_at = time.time()
        elif state == "SUCCESS":
            job.status = "succeeded"
            job.finished_at = job.finished_at or time.time()
            try:
                job.result = async_result.result
            except Exception:  # noqa: BLE001
                job.result = None
            if job.cache_key and self._redis is not None and job.result is not None:
                try:
                    self._redis.hset("mtg:results", job.cache_key, json.dumps(job.result, default=_serialize_arg))
                except Exception:  # noqa: BLE001
                    pass
        elif state == "FAILURE":
            job.status = "failed"
            job.finished_at = job.finished_at or time.time()
            job.error = str(async_result.result) if async_result.result else "task failed"
        elif state == "RETRY":
            job.status = "running"
        return job

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())


def _serialize_arg(obj: Any) -> Any:
    """JSON encoder hook for dataclasses and Pydantic models."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
