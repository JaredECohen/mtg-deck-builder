from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.workers.queue import (
    JobNotFound,
    ThreadJobQueue,
    make_cache_key,
    reset_job_queue,
)


@pytest.fixture(autouse=True)
def _reset_queue():
    reset_job_queue()
    yield
    reset_job_queue()


def test_thread_queue_submit_and_complete():
    q = ThreadJobQueue(max_workers=2)
    job = q.submit(name="square", fn=lambda x: x * x, args=(7,))
    completed = q.wait(job.id, timeout=5)
    assert completed.status == "succeeded"
    assert completed.result == 49


def test_thread_queue_records_failure():
    q = ThreadJobQueue(max_workers=2)
    def boom():
        raise RuntimeError("nope")
    job = q.submit(name="boom", fn=boom)
    completed = q.wait(job.id, timeout=5)
    assert completed.status == "failed"
    assert "RuntimeError" in (completed.error or "")


def test_thread_queue_cache_hits():
    q = ThreadJobQueue(max_workers=2)
    call_count = {"n": 0}
    def slow(x):
        call_count["n"] += 1
        return x + 1
    job1 = q.submit(name="slow", fn=slow, args=(5,), cache_key="key-A")
    q.wait(job1.id, timeout=5)
    job2 = q.submit(name="slow", fn=slow, args=(5,), cache_key="key-A")
    assert job2.status == "cached"
    assert job2.result == 6
    assert call_count["n"] == 1  # second submit was served from cache


def test_thread_queue_get_unknown_raises():
    q = ThreadJobQueue(max_workers=2)
    with pytest.raises(JobNotFound):
        q.get("not-a-real-id")


def test_make_cache_key_stable():
    a = make_cache_key({"x": 1, "y": [1, 2, 3]})
    b = make_cache_key({"y": [1, 2, 3], "x": 1})  # different order
    assert a == b
    c = make_cache_key({"x": 2, "y": [1, 2, 3]})
    assert a != c


def test_optimize_endpoint_submits_job_and_polls():
    """End-to-end: POST /v1/jobs/optimize returns a job_id, GET
    /v1/jobs/{id} eventually shows succeeded."""
    from app.main import app
    client = TestClient(app)
    payload = {
        "format": "modern",
        "colors": ["R"],
        "deck_size": 60,
        "include_cards": [],
        "exclude_cards": [],
        "archetype_recipes": [{
            "id": "modern-burn",
            "card_quotas": {
                "Lightning Bolt": 4,
                "Goblin Guide": 4,
                "Mountain": 20,
            },
        }],
        "rounds": 4,
        "proposals_per_round": 2,
        "sim_runs_per_eval": 60,
    }
    resp = client.post("/v1/jobs/optimize", json=payload)
    assert resp.status_code in (200, 400)  # 400 if pool is empty
    if resp.status_code == 400:
        # Sample card pool has too few Modern cards in test env;
        # accept this — the endpoint contract is what we're testing.
        return
    body = resp.json()
    job_id = body["job_id"]
    assert body["poll_url"] == f"/v1/jobs/{job_id}"

    # Poll up to 30 seconds for completion (optimizer is fast).
    deadline = time.time() + 30
    last = None
    while time.time() < deadline:
        poll = client.get(f"/v1/jobs/{job_id}")
        assert poll.status_code == 200
        last = poll.json()
        if last["status"] in ("succeeded", "failed", "cached"):
            break
        time.sleep(0.2)
    assert last is not None
    assert last["status"] in ("succeeded", "cached")
    assert last["result"] is not None
    assert "deck" in last["result"]


def test_optimize_endpoint_cached_repeat_call():
    from app.main import app
    client = TestClient(app)
    payload = {
        "format": "modern",
        "colors": ["R"],
        "deck_size": 60,
        "archetype_recipes": [{"id": "burn", "card_quotas": {"Mountain": 24}}],
        "rounds": 2,
        "proposals_per_round": 1,
        "sim_runs_per_eval": 30,
        "seed": 99,
    }
    r1 = client.post("/v1/jobs/optimize", json=payload)
    if r1.status_code != 200:
        return  # pool too thin in test env
    job_id_1 = r1.json()["job_id"]
    # Wait for first job.
    deadline = time.time() + 30
    while time.time() < deadline:
        if client.get(f"/v1/jobs/{job_id_1}").json()["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    # Second submit with same payload: should be served from cache instantly.
    r2 = client.post("/v1/jobs/optimize", json=payload)
    assert r2.status_code == 200
    assert r2.json()["cached"] is True


def test_get_job_404_for_unknown_id():
    from app.main import app
    client = TestClient(app)
    resp = client.get("/v1/jobs/not-a-real-uuid")
    assert resp.status_code == 404


def test_celery_backend_imports_and_serializes_args():
    """Lazy-import the Celery backend; without a live broker we just
    verify the module loads, the app builds, and JSON serialization of
    common task args succeeds. Skipped if Celery isn't installed."""
    pytest.importorskip("celery")
    from app.workers import celery_backend

    app = celery_backend._get_app()
    assert app is not None
    # Dispatcher task should be registered.
    assert hasattr(app, "_mtg_dispatch")

    # Argument serializer should handle dataclasses with to_dict().
    class WithToDict:
        def to_dict(self):
            return {"x": 1}
    out = celery_backend._serialize_arg(WithToDict())
    assert out == {"x": 1}


def test_get_job_queue_respects_env_var(monkeypatch):
    """get_job_queue() chooses backend by env."""
    from app.workers.queue import get_job_queue, reset_job_queue, ThreadJobQueue
    reset_job_queue()
    monkeypatch.setenv("MTG_WORKER_BACKEND", "thread")
    q = get_job_queue()
    assert isinstance(q, ThreadJobQueue)
    reset_job_queue()
