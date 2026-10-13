"""CI gate over the deterministic deck-generation benchmark (plan item C2).

Runs the fixed 40-scenario gate subset of ``qa/benchmark.py`` in-process
against the suite's fixture DB (conftest sets ``DATABASE_URL`` before the app
is imported), with the LLM disabled, and checks per-metric pass rates.

Two kinds of test per metric:

* ``test_metric_floor``: the pass rate the code achieved when the gate was
  written (2026-10-12, fixture DB). Dropping below it is a regression. Raise a
  floor when the engine improves; never lower one to make CI green.
* ``test_metric_target``: the plan's target. Where the engine is not there yet
  the test is ``xfail(strict=False)``, so it reports XPASS once the engine
  lands the fix. When that happens, drop the xfail and raise the floor.

Full matrix, metric definitions and how to add scenarios: ``qa/README.md``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_BENCHMARK_PATH = Path(__file__).resolve().parents[2] / "qa" / "benchmark.py"


def _load_benchmark():
    spec = importlib.util.spec_from_file_location("qa_benchmark", _BENCHMARK_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["qa_benchmark"] = module
    spec.loader.exec_module(module)
    return module


benchmark = _load_benchmark()


@pytest.fixture(scope="module")
def gate_report():
    from app import rate_limiter
    from app.main import app, repository
    from app.services import llm_service

    with pytest.MonkeyPatch.context() as mp:
        # LLM-free: no key means every LLM helper takes its deterministic path.
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MTG_API_KEY", "MTG_USE_OPTIMIZER_DEFAULT"):
            mp.setenv(key, "")
        mp.setattr(llm_service, "_client", None)
        # 40 generations plus refines exceed the per-IP limits in one minute.
        mp.setattr(rate_limiter.InMemoryRateLimiter, "is_allowed", lambda self, key: True)
        mp.setattr(repository, "refresh_service", None)
        report = benchmark.run_benchmark(TestClient(app), repository, benchmark.gate_scenarios())
    return report["summary"]["overall"]


# Measured on the fixture DB at 3e0672e (feat/spec-gaps API contract commit):
# http 40/40, legality 40/40, deck size 40/40, lands 40/40, color 32/32,
# budget 16/18, sideboard 9/28, bracket 0/8, refine 11/24, prompt 2/8.
FLOORS = {
    "http_success": 1.0,
    "legality": 1.0,
    "deck_size": 1.0,
    "land_count": 1.0,
    "color_fidelity": 1.0,
    "budget_adherence": 0.88,
    "sideboard_completeness": 0.32,
    "refine_success": 0.45,
    "prompt_fidelity": 0.25,
    # bracket_compliance is 0/8 today (no assessment is returned yet), so it
    # has no floor; its target test below tracks it.
}

_PENDING = "engine fix in progress (feat/spec-gaps stream A)"
TARGETS = [
    pytest.param("legality", 1.0, id="legality"),
    pytest.param("color_fidelity", 0.95, id="color_fidelity"),
    pytest.param("budget_adherence", 0.90, id="budget_adherence",
                 marks=pytest.mark.xfail(strict=False, reason=f"budget: {_PENDING} (A2)")),
    pytest.param("sideboard_completeness", 1.0, id="sideboard_completeness",
                 marks=pytest.mark.xfail(strict=False, reason=f"15-card bo3 / empty bo1 sideboard: {_PENDING} (A3)")),
    pytest.param("bracket_compliance", 1.0, id="bracket_compliance",
                 marks=pytest.mark.xfail(strict=False, reason=f"bracket assessment and filtering: {_PENDING} (A7)")),
    pytest.param("refine_success", 1.0, id="refine_success",
                 marks=pytest.mark.xfail(strict=False, reason=f"excludes leak into the sideboard on refine: {_PENDING} (A1/A2)")),
    pytest.param("prompt_fidelity", 0.90, id="prompt_fidelity",
                 marks=pytest.mark.xfail(strict=False, reason=f"no-LLM prompt intent parser: {_PENDING} (A4)")),
]


def _describe(metric: str, stats: dict) -> str:
    failures = "; ".join(f"{f['id']}: {f['detail']}" for f in stats["failures"][:8])
    return f"{metric} {stats['passed']}/{stats['n']} = {stats['rate']}. Failing: {failures}"


def test_gate_subset_shape(gate_report):
    scenarios = benchmark.gate_scenarios()
    assert 35 <= len(scenarios) <= 45
    assert {s.format for s in scenarios} == set(benchmark.ALL_FORMATS)
    assert {s.group for s in scenarios} == {"constructed", "commander", "prompt"}
    for metric in FLOORS:
        assert gate_report[metric]["n"] > 0, f"{metric} had no applicable scenarios"


@pytest.mark.parametrize("metric,floor", sorted(FLOORS.items()))
def test_metric_floor(gate_report, metric, floor):
    stats = gate_report[metric]
    assert stats["rate"] is not None and stats["rate"] >= floor, _describe(metric, stats)


@pytest.mark.parametrize("metric,target", TARGETS)
def test_metric_target(gate_report, metric, target):
    stats = gate_report[metric]
    assert stats["rate"] is not None and stats["rate"] >= target, _describe(metric, stats)
