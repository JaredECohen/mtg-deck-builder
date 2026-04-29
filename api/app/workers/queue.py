"""Async job queue interface + ThreadPoolExecutor backend."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

JobStatus = str  # "pending" | "running" | "succeeded" | "failed" | "cached"


@dataclass
class Job:
    id: str
    name: str
    status: JobStatus = "pending"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: str | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    cache_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
            "progress": dict(self.progress),
        }


class JobNotFound(KeyError):
    pass


class JobQueue:
    """Abstract base for any job queue backend."""

    def submit(
        self,
        name: str,
        fn: Callable[..., Any],
        *,
        args: Iterable[Any] = (),
        kwargs: dict[str, Any] | None = None,
        cache_key: str | None = None,
    ) -> Job:
        raise NotImplementedError

    def get(self, job_id: str) -> Job:
        raise NotImplementedError

    def list(self) -> list[Job]:
        raise NotImplementedError


class ThreadJobQueue(JobQueue):
    """In-process queue using ThreadPoolExecutor.

    Suitable for dev, tests, and small deployments. Job state is held
    in memory; restart loses it. Result caching is process-local —
    keyed by an explicit ``cache_key`` argument to ``submit``.
    """

    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mtg-worker")
        self._jobs: dict[str, Job] = {}
        self._futures: dict[str, Future] = {}
        self._cache: dict[str, Any] = {}
        self._lock = threading.RLock()

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
        with self._lock:
            if cache_key and cache_key in self._cache:
                job = Job(
                    id=str(uuid.uuid4()),
                    name=name,
                    status="cached",
                    started_at=time.time(),
                    finished_at=time.time(),
                    result=self._cache[cache_key],
                    cache_key=cache_key,
                )
                self._jobs[job.id] = job
                return job
            job = Job(id=str(uuid.uuid4()), name=name, status="pending", cache_key=cache_key)
            self._jobs[job.id] = job

        def _run() -> Any:
            with self._lock:
                job.status = "running"
                job.started_at = time.time()
            try:
                try:
                    result = fn(*args, _job_progress=job.progress, **kwargs)
                except TypeError as exc:
                    # ``_job_progress`` not accepted — retry without it,
                    # but only if the TypeError is *about* the kwarg.
                    if "_job_progress" not in str(exc):
                        raise
                    result = fn(*args, **kwargs)
            except Exception:
                tb = traceback.format_exc()
                with self._lock:
                    job.status = "failed"
                    job.error = tb
                    job.finished_at = time.time()
                raise
            with self._lock:
                job.status = "succeeded"
                job.result = result
                job.finished_at = time.time()
                if cache_key:
                    self._cache[cache_key] = result
            return result

        future = self._executor.submit(_run)
        self._futures[job.id] = future
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            if job_id not in self._jobs:
                raise JobNotFound(job_id)
            return self._jobs[job_id]

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def wait(self, job_id: str, timeout: float | None = None) -> Job:
        future = self._futures.get(job_id)
        if future is not None:
            try:
                future.result(timeout=timeout)
            except Exception:
                pass  # status already recorded
        return self.get(job_id)


_default_queue: JobQueue | None = None
_default_lock = threading.Lock()


def get_job_queue() -> JobQueue:
    global _default_queue
    with _default_lock:
        if _default_queue is None:
            backend = os.getenv("MTG_WORKER_BACKEND", "thread").lower()
            if backend == "celery":
                # Lazily import to avoid hard dependency in dev/test.
                from app.workers.celery_backend import CeleryJobQueue  # type: ignore
                _default_queue = CeleryJobQueue()
            else:
                _default_queue = ThreadJobQueue(
                    max_workers=int(os.getenv("MTG_WORKER_THREADS", "4"))
                )
        return _default_queue


def reset_job_queue() -> None:
    """Reset the singleton — for tests only."""
    global _default_queue
    with _default_lock:
        _default_queue = None


def make_cache_key(payload: dict[str, Any]) -> str:
    """Stable hash of a JSON-serializable payload for cache keys."""
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()
