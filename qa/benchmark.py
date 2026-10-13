#!/usr/bin/env python
"""Deterministic, LLM-free deck-generation benchmark (spec §21, plan item C1).

Runs a generated scenario matrix in-process against the FastAPI app through
``TestClient`` and scores every returned deck on objective metrics: HTTP
success, legality (re-validated through ``/v1/decks/validate``), color
fidelity, budget adherence, land-count sanity, deck size, sideboard
completeness, Commander bracket compliance, scripted-refine success,
prompt-intent fidelity of the no-LLM path, and per-endpoint latency.

Usage (from the repo root or from ``api/``; the script finds the app itself)::

    api/.venv/bin/python qa/benchmark.py                       # fixture DB
    api/.venv/bin/python qa/benchmark.py --database-url sqlite:////abs/path/full.db
    api/.venv/bin/python qa/benchmark.py --limit 20            # quick smoke run

Outputs ``qa/artifacts/benchmark.json`` (gitignored, full per-scenario detail)
and ``qa/BENCHMARK.md`` (committed summary). See ``qa/README.md``.

The module is importable without side effects: scenario generation and
scoring take the client and repository as arguments, so
``api/tests/test_benchmark_gate.py`` reuses them against the test suite's
fixture DB. Only ``main()`` touches the environment and imports the app.
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

QA_DIR = Path(__file__).resolve().parent
ROOT = QA_DIR.parent
API_DIR = ROOT / "api"
FIXTURE_DB = API_DIR / "tests" / "fixtures" / "cards.db.gz"
DEFAULT_JSON = QA_DIR / "artifacts" / "benchmark.json"
DEFAULT_SUMMARY = QA_DIR / "BENCHMARK.md"

# ---------------------------------------------------------------------------
# Scenario matrix
# ---------------------------------------------------------------------------

CONSTRUCTED_FORMATS = ["standard", "pioneer", "modern", "legacy"]
ALL_FORMATS = CONSTRUCTED_FORMATS + ["commander"]
MONO = ["W", "U", "B", "R", "G"]
GUILDS = [["W", "U"], ["U", "B"], ["B", "R"], ["R", "G"], ["G", "W"],
          ["W", "B"], ["U", "R"], ["B", "G"], ["R", "W"], ["G", "U"]]
SHARDS = [["W", "U", "B"], ["U", "B", "R"], ["B", "R", "G"], ["R", "G", "W"], ["G", "W", "U"],
          ["W", "B", "G"], ["U", "R", "W"], ["B", "G", "U"], ["R", "W", "B"], ["G", "U", "R"]]
PLAYSTYLES = ["aggro", "control", "midrange", "combo", "tokens", "ramp", "spells", "tribal", "tempo"]
MODES = ["constraint-aware", "fast-competitive", "creative-but-viable"]
# Budget tiers are per format: $40 is a real Standard budget but not a Legacy one.
BUDGET_TIERS: dict[str, dict[str, float]] = {
    "standard": {"low": 50.0, "mid": 150.0},
    "pioneer": {"low": 60.0, "mid": 200.0},
    "modern": {"low": 80.0, "mid": 300.0},
    "legacy": {"low": 150.0, "mid": 600.0},
    "commander": {"low": 75.0, "mid": 250.0},
}
TIER_ORDER = ["none", "low", "mid"]
# Commanders present in both the CI fixture and the full ingest.
EXPLICIT_COMMANDERS = [
    "Krenko, Mob Boss", "Sheoldred, Whispering One", "Talrand, Sky Summoner",
    "Light-Paws, Emperor's Voice", "Lathril, Blade of the Elves", "Niv-Mizzet, Parun",
    "Kaalia of the Vast", "Ghave, Guru of Spores", "Atraxa, Praetors' Voice",
    "Kenrith, the Returned King",
]
BRACKETS: list[int | None] = [None, 1, 2, 3, 4, 5]

# Natural-language prompts: only `format` + `prompt` are sent. Expectations
# describe what a correct reading of the prompt must produce.
#   allowed: every card's color identity must be a subset (None = unchecked)
#   required: each color must appear on >=1 nonland card (defaults to allowed)
#   max_price: estimated price ceiling
#   commander: substring the chosen commander's name must contain
PROMPTS: list[dict[str, Any]] = [
    {"format": "standard", "prompt": "cheap mono-green stompy under $40", "allowed": "G", "max_price": 40},
    {"format": "modern", "prompt": "Izzet prowess with lots of burn", "allowed": "UR"},
    {"format": "pioneer", "prompt": "Rakdos midrange, budget $100", "allowed": "BR", "max_price": 100},
    {"format": "legacy", "prompt": "mono-red burn", "allowed": "R"},
    {"format": "commander", "prompt": "Golgari graveyard recursion deck", "allowed": "BG"},
    {"format": "commander", "prompt": "Mardu aristocrats under $150", "allowed": "RWB", "max_price": 150},
    {"format": "modern", "prompt": "Azorius control deck with counterspells", "allowed": "WU"},
    {"format": "standard", "prompt": "Boros aggro with tokens", "allowed": "RW"},
    {"format": "pioneer", "prompt": "mono-black midrange", "allowed": "B"},
    {"format": "modern", "prompt": "Esper midrange under $200", "allowed": "WUB", "max_price": 200},
    {"format": "legacy", "prompt": "Dimir tempo", "allowed": "UB"},
    {"format": "commander", "prompt": "mono-white equipment voltron", "allowed": "W"},
    {"format": "standard", "prompt": "Simic ramp with big creatures", "allowed": "GU"},
    {"format": "modern", "prompt": "cheap Gruul ramp", "allowed": "RG"},
    {"format": "commander", "prompt": "Temur spellslinger, $100 budget", "allowed": "GUR", "max_price": 100},
    {"format": "pioneer", "prompt": "Orzhov lifegain under $60", "allowed": "WB", "max_price": 60},
    {"format": "modern", "prompt": "Selesnya tokens go-wide", "allowed": "GW"},
    {"format": "commander", "prompt": "Krenko goblins tribal", "allowed": "R", "commander": "Krenko"},
    {"format": "standard", "prompt": "blue-black control", "allowed": "UB"},
    {"format": "legacy", "prompt": "Jund midrange under $500", "allowed": "BRG", "max_price": 500},
    {"format": "commander", "prompt": "Abzan +1/+1 counters", "allowed": "WBG"},
    {"format": "pioneer", "prompt": "white weenie aggro", "allowed": "W"},
    {"format": "modern", "prompt": "colorless Eldrazi Tron", "allowed": "", "required": ""},
    {"format": "standard", "prompt": "red deck wins under $30", "allowed": "R", "max_price": 30},
]


@dataclass
class Scenario:
    id: str
    group: str  # constructed | commander | prompt
    format: str
    request: dict[str, Any]
    expect: dict[str, Any] = field(default_factory=dict)
    refine: bool = False  # run the scripted refine on the generated deck
    gate: bool = False  # part of the CI gate subset


def _slug(colors: list[str]) -> str:
    if colors == ["C"]:
        return "colorless"
    return "".join(colors).lower() or "anycolor"


def generate_scenarios() -> list[Scenario]:
    """The full matrix, deterministic (no randomness, no DB access)."""
    scenarios: list[Scenario] = []

    for f, fmt in enumerate(CONSTRUCTED_FORMATS):
        color_specs: list[list[str]] = [[c] for c in MONO]
        color_specs += [GUILDS[(f * 5 + k) % len(GUILDS)] for k in range(5)]
        color_specs += [SHARDS[(f * 3 + k) % len(SHARDS)] for k in range(3)]
        color_specs += [["C"], []]
        for i, colors in enumerate(color_specs):
            playstyle = PLAYSTYLES[(i + f * 2) % len(PLAYSTYLES)]
            tier = TIER_ORDER[(i * 2 + f) % 3]
            mode = MODES[(i + f + i // 3) % 3]
            match_type = "bo3" if (i + f) % 2 == 0 else "bo1"
            request: dict[str, Any] = {
                "format": fmt,
                "colors": colors,
                "playstyle_tags": [playstyle],
                "mode": mode,
                "match_type": match_type,
            }
            if tier != "none":
                request["budget"] = BUDGET_TIERS[fmt][tier]
            sid = f"{fmt}-{_slug(colors)}-{playstyle}-{tier}-{mode.split('-')[0]}-{match_type}"
            scenarios.append(Scenario(
                id=sid, group="constructed", format=fmt, request=request,
                expect={"budget_tier": tier},
                refine=i % 3 == 0, gate=i % 3 == 0,
            ))

    commander_specs: list[tuple[list[str], str | None]] = [([c], None) for c in MONO]
    commander_specs += [(GUILDS[k], None) for k in (1, 3, 5, 7)]
    commander_specs += [(SHARDS[k], None) for k in (0, 5, 9)]
    commander_specs += [([], None), (["C"], None)]
    commander_specs += [([], name) for name in EXPLICIT_COMMANDERS]
    for i, (colors, commander) in enumerate(commander_specs):
        bracket = BRACKETS[i % len(BRACKETS)]
        playstyle = PLAYSTYLES[(i * 2) % len(PLAYSTYLES)]
        tier = TIER_ORDER[(i + i // 3) % 3]
        mode = MODES[(i // 2) % 3]
        request = {"format": "commander", "colors": colors, "playstyle_tags": [playstyle], "mode": mode}
        if commander:
            request["commander_name"] = commander
        if bracket is not None:
            request["bracket"] = bracket
        if tier != "none":
            request["budget"] = BUDGET_TIERS["commander"][tier]
        who = commander.split(",")[0].split(" of ")[0].lower().replace(" ", "") if commander else _slug(colors)
        sid = f"commander-{who}-{playstyle}-{tier}-{mode.split('-')[0]}-b{bracket or 'none'}"
        scenarios.append(Scenario(
            id=sid, group="commander", format="commander", request=request,
            expect={"budget_tier": tier, "commander": commander},
            refine=i % 3 == 0, gate=i % 2 == 0,
        ))

    for i, item in enumerate(PROMPTS):
        allowed = item["allowed"]
        required = item.get("required", allowed)
        words = "".join(ch if ch.isalnum() else "-" for ch in item["prompt"].lower()).strip("-")
        sid = f"prompt-{item['format']}-{'-'.join(w for w in words.split('-') if w)[:40]}"
        scenarios.append(Scenario(
            id=sid, group="prompt", format=item["format"],
            request={"format": item["format"], "prompt": item["prompt"]},
            expect={
                "allowed": list(allowed) if allowed is not None else None,
                "required": list(required) if required is not None else None,
                "max_price": item.get("max_price"),
                "commander": item.get("commander"),
            },
            gate=i % 3 == 0,
        ))
    return scenarios


def gate_scenarios() -> list[Scenario]:
    return [s for s in generate_scenarios() if s.gate]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

METRICS = [
    "http_success",
    "legality",
    "deck_size",
    "land_count",
    "color_fidelity",
    "budget_adherence",
    "sideboard_completeness",
    "bracket_compliance",
    "refine_success",
    "prompt_fidelity",
]
METRIC_HELP = {
    "http_success": "generate returned HTTP 200",
    "legality": "returned list re-validated via /v1/decks/validate is legal",
    "deck_size": "constructed main = 60; commander main = 99 + commander",
    "land_count": "constructed 14-28 lands; commander 30-42",
    "color_fidelity": "no card outside requested colors / commander identity, every requested color on a nonland card",
    "budget_adherence": "recomputed price (main + side + commander) <= requested budget",
    "sideboard_completeness": "constructed bo3 sideboard = 15, bo1 = 0",
    "bracket_compliance": "bracket.estimated <= max(target, 2) (a list shows a floor of 2), and no game changers when target <= 2",
    "refine_success": "scripted refine drops the excluded card, adds the included one, keeps lands, stays legal",
    "prompt_fidelity": "prompt-only request honors the prompt's colors / price / commander",
}

LAND_RANGE = {"constructed": (14, 28), "commander": (30, 42)}


@dataclass
class Check:
    ok: bool | None  # None = not applicable
    detail: str = ""


def _total(refs: list[dict[str, Any]]) -> int:
    return sum(int(r["quantity"]) for r in refs)


def _identity(card: Any) -> set[str]:
    return set(card.color_identity or []) if card is not None else set()


def _fmt_colors(colors: set[str] | list[str]) -> str:
    return "".join(sorted(colors)) or "C"


class Timer:
    def __init__(self) -> None:
        self.samples: dict[str, list[float]] = {}

    @contextlib.contextmanager
    def time(self, endpoint: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.samples.setdefault(endpoint, []).append((time.perf_counter() - start) * 1000)


def _cards(repository: Any, deck: dict[str, Any]) -> dict[str, Any]:
    names = {r["name"] for r in deck.get("mainboard", []) + deck.get("sideboard", [])}
    if deck.get("commander"):
        names.add(deck["commander"])
    return {name: repository.get_card(name) for name in names}


def _land_count(deck: dict[str, Any], cards: dict[str, Any]) -> int:
    from app.rules import is_land_card

    return sum(int(r["quantity"]) for r in deck["mainboard"]
               if cards.get(r["name"]) is not None and is_land_card(cards[r["name"]]))


def _price(deck: dict[str, Any], cards: dict[str, Any]) -> tuple[float, list[str]]:
    total = 0.0
    unpriced: list[str] = []
    refs = list(deck["mainboard"]) + list(deck.get("sideboard", []))
    if deck.get("commander"):
        refs.append({"name": deck["commander"], "quantity": 1})
    for ref in refs:
        card = cards.get(ref["name"])
        price = getattr(card, "price_usd", None) if card is not None else None
        if price is None:
            unpriced.append(ref["name"])
        else:
            total += float(price) * int(ref["quantity"])
    return round(total, 2), sorted(set(unpriced))


def _validate(client: Any, timer: Timer, deck: dict[str, Any]) -> tuple[bool, list[str]]:
    body = {
        "format": deck["format"],
        "mainboard": deck["mainboard"],
        "sideboard": deck.get("sideboard", []),
        "commander": deck.get("commander"),
    }
    with timer.time("validate"):
        resp = client.post("/v1/decks/validate", json=body)
    if resp.status_code != 200:
        return False, [f"validate HTTP {resp.status_code}: {resp.text[:160]}"]
    data = resp.json()
    return bool(data.get("is_legal")), list(data.get("errors", []))


def _color_check(
    deck: dict[str, Any], cards: dict[str, Any], allowed: set[str] | None, required: set[str],
) -> Check:
    from app.rules import is_land_card

    problems: list[str] = []
    if allowed is not None:
        off = []
        for ref in deck["mainboard"] + deck.get("sideboard", []):
            ident = _identity(cards.get(ref["name"]))
            if not ident <= allowed:
                off.append(f"{ref['name']} ({_fmt_colors(ident)})")
        if deck.get("commander"):
            ident = _identity(cards.get(deck["commander"]))
            if not ident <= allowed:
                off.insert(0, f"commander {deck['commander']} ({_fmt_colors(ident)})")
        if off:
            problems.append(f"off-color vs {_fmt_colors(allowed)}: " + ", ".join(sorted(set(off))[:6])
                            + (f" (+{len(set(off)) - 6} more)" if len(set(off)) > 6 else ""))
    if required:
        present: set[str] = set()
        nonland_names = [r["name"] for r in deck["mainboard"]]
        if deck.get("commander"):
            nonland_names.append(deck["commander"])
        for name in nonland_names:
            card = cards.get(name)
            if card is not None and not is_land_card(card):
                present |= _identity(card)
        missing = required - present
        if missing:
            problems.append(f"requested color(s) {_fmt_colors(missing)} on no nonland card")
    if allowed is None and not required:
        return Check(None)
    return Check(not problems, "; ".join(problems))


def _pick_refine_cards(
    repository: Any, deck: dict[str, Any], cards: dict[str, Any], scenario_id: str,
) -> tuple[str | None, str | None]:
    """Deterministically pick a card to cut and an on-color, legal, cheap card to add."""
    from app.rules import is_basic_land, is_land_card

    commander = (deck.get("commander") or "").lower()
    cuttable = sorted(
        r["name"] for r in deck["mainboard"]
        if cards.get(r["name"]) is not None
        and not is_land_card(cards[r["name"]])
        and r["name"].lower() != commander
    )
    if not cuttable:
        return None, None
    digest = int(hashlib.sha256(scenario_id.encode()).hexdigest(), 16)
    cut = cuttable[digest % len(cuttable)]

    if deck.get("commander"):
        identity = _identity(cards.get(deck["commander"]))
    else:
        identity = set()
        for name, card in cards.items():
            if card is not None and not is_land_card(card):
                identity |= _identity(card)
    in_deck = {r["name"].lower() for r in deck["mainboard"] + deck.get("sideboard", [])} | {commander}
    fmt = deck["format"]
    candidates = sorted(
        c.name for c in repository.all_cards()
        if c.legalities.get(fmt) == "legal"
        and not is_land_card(c) and not is_basic_land(c)
        and set(c.color_identity or []) <= identity
        and c.price_usd is not None and c.price_usd <= 1.0
        and c.name.lower() not in in_deck
        and " // " not in c.name
    )
    if not candidates:
        return cut, None
    return cut, candidates[(digest // 7) % len(candidates)]


@contextlib.contextmanager
def scripted_refinement(intent: Any) -> Iterator[None]:
    """Make ``/v1/decks/refine`` use ``intent`` instead of the LLM interpreter."""
    from app.services import deck_generator

    original = deck_generator.interpret_refinement
    deck_generator.interpret_refinement = lambda prompt: intent
    try:
        yield
    finally:
        deck_generator.interpret_refinement = original


def _refine_check(
    client: Any, repository: Any, timer: Timer, scenario: Scenario,
    deck: dict[str, Any], cards: dict[str, Any],
) -> tuple[Check, dict[str, Any]]:
    from app.services.llm_service import RefinementIntent

    cut, add = _pick_refine_cards(repository, deck, cards, scenario.id)
    info: dict[str, Any] = {"excluded": cut, "included": add}
    if cut is None or add is None:
        return Check(False, f"could not pick refine cards (cut={cut}, add={add})"), info
    intent = RefinementIntent(exclude_cards=[cut], include_cards=[add])
    with scripted_refinement(intent):
        with timer.time("refine"):
            resp = client.post("/v1/decks/refine", json={"deck": deck, "refinement_prompt": f"cut {cut}, add {add}"})
    if resp.status_code != 200:
        return Check(False, f"refine HTTP {resp.status_code}: {resp.text[:160]}"), info
    refined = resp.json()
    refined_cards = _cards(repository, refined)
    problems = []
    main_left = sum(r["quantity"] for r in refined["mainboard"] if r["name"] == cut)
    side_left = sum(r["quantity"] for r in refined.get("sideboard", []) if r["name"] == cut)
    if main_left or side_left:
        before_main = sum(r["quantity"] for r in deck["mainboard"] if r["name"] == cut)
        problems.append(f"excluded {cut} still present (main {before_main}->{main_left}, side {side_left})")
    if add not in {r["name"] for r in refined["mainboard"]}:
        problems.append(f"included {add} missing")
    before, after = _land_count(deck, cards), _land_count(refined, refined_cards)
    if before != after:
        problems.append(f"lands {before}->{after}")
    legal, errors = _validate(client, timer, refined)
    if not legal:
        problems.append("illegal after refine: " + "; ".join(errors[:2]))
    info.update({"lands_before": before, "lands_after": after})
    return Check(not problems, "; ".join(problems)), info


def run_scenario(client: Any, repository: Any, scenario: Scenario, timer: Timer) -> dict[str, Any]:
    checks: dict[str, Check] = {}
    result: dict[str, Any] = {
        "id": scenario.id, "group": scenario.group, "format": scenario.format,
        "request": scenario.request,
    }
    with timer.time("generate"):
        resp = client.post("/v1/decks/generate", json=scenario.request)
    checks["http_success"] = Check(resp.status_code == 200, "" if resp.status_code == 200 else f"HTTP {resp.status_code}: {resp.text[:200]}")
    if resp.status_code != 200:
        result["checks"] = {k: asdict(v) for k, v in checks.items()}
        return result

    deck = resp.json()
    cards = _cards(repository, deck)
    is_commander = scenario.format == "commander"
    match_type = scenario.request.get("match_type", "bo3")

    legal, errors = _validate(client, timer, deck)
    checks["legality"] = Check(legal, "; ".join(errors[:3]))
    if bool(deck.get("is_legal")) != legal:
        checks["legality"].detail = (checks["legality"].detail + f" (response is_legal={deck.get('is_legal')})").strip()

    main_total = _total(deck["mainboard"])
    if is_commander:
        ok = main_total == 99 and bool(deck.get("commander"))
        checks["deck_size"] = Check(ok, "" if ok else f"main={main_total}, commander={deck.get('commander')}")
    else:
        checks["deck_size"] = Check(main_total == 60, "" if main_total == 60 else f"main={main_total}")

    lands = _land_count(deck, cards)
    lo, hi = LAND_RANGE["commander" if is_commander else "constructed"]
    checks["land_count"] = Check(lo <= lands <= hi, "" if lo <= lands <= hi else f"{lands} lands (want {lo}-{hi})")

    # Color fidelity (explicit requests) and prompt fidelity (prompt-only requests).
    req_colors = [c for c in scenario.request.get("colors", [])]
    if scenario.group == "prompt":
        exp = scenario.expect
        allowed = set(exp["allowed"]) if exp.get("allowed") is not None else None
        required = set(exp.get("required") or [])
        parts = []
        color = _color_check(deck, cards, allowed, required)
        if color.ok is False:
            parts.append(color.detail)
        price, unpriced = _price(deck, cards)
        if exp.get("max_price") is not None and price > exp["max_price"]:
            parts.append(f"price ${price:.2f} > ${exp['max_price']}")
        if exp.get("commander") and exp["commander"].lower() not in (deck.get("commander") or "").lower():
            parts.append(f"commander {deck.get('commander')!r}, expected {exp['commander']!r}")
        checks["prompt_fidelity"] = Check(not parts, "; ".join(parts))
        checks["color_fidelity"] = Check(None)
        checks["budget_adherence"] = Check(None)
    else:
        checks["prompt_fidelity"] = Check(None)
        if is_commander:
            commander_card = cards.get(deck.get("commander") or "")
            cmd_identity = _identity(commander_card)
            requested = {c for c in req_colors if c != "C"}
            if "C" in req_colors and not requested:
                allowed, required = set(), set()
            elif requested:
                allowed, required = requested, requested
            else:
                allowed, required = cmd_identity, set()
            parts = []
            color = _color_check(deck, cards, allowed, required)
            if color.ok is False:
                parts.append(color.detail)
            want = scenario.expect.get("commander")
            if want and (deck.get("commander") or "").lower() != want.lower():
                parts.append(f"commander {deck.get('commander')!r} != requested {want!r}")
            checks["color_fidelity"] = Check(not parts, "; ".join(parts))
        elif req_colors:
            requested = {c for c in req_colors if c != "C"}
            checks["color_fidelity"] = _color_check(deck, cards, requested, requested)
        else:
            checks["color_fidelity"] = Check(None)

        budget = scenario.request.get("budget")
        price, unpriced = _price(deck, cards)
        if budget is None:
            checks["budget_adherence"] = Check(None)
        else:
            ok = price <= budget
            detail = "" if ok else f"price ${price:.2f} > budget ${budget:.0f}"
            if unpriced:
                detail = (detail + f" ({len(unpriced)} unpriced)").strip()
            checks["budget_adherence"] = Check(ok, detail)

    price, unpriced = _price(deck, cards)
    result["price"] = {"recomputed": price, "reported": deck.get("estimated_price_usd"), "unpriced": unpriced}

    if is_commander:
        checks["sideboard_completeness"] = Check(None)
    else:
        side = _total(deck.get("sideboard", []))
        want = 15 if match_type == "bo3" else 0
        checks["sideboard_completeness"] = Check(side == want, "" if side == want else f"{match_type} sideboard={side} (want {want})")

    target = scenario.request.get("bracket")
    if target is None:
        checks["bracket_compliance"] = Check(None)
    else:
        assessment = deck.get("bracket")
        if not assessment:
            checks["bracket_compliance"] = Check(False, "no bracket assessment in response")
        else:
            parts = []
            est = assessment.get("estimated")
            # A list can only show a floor of bracket 2: bracket 1 (Exhibition)
            # is about theme and table intent (see app/services/brackets.py).
            if est is None or est > max(target, 2):
                parts.append(f"estimated {est} > target {target}")
            gcs = assessment.get("game_changers") or []
            if target <= 2 and gcs:
                parts.append("game changers: " + ", ".join(gcs[:5]))
            checks["bracket_compliance"] = Check(not parts, "; ".join(parts))

    if scenario.refine:
        check, info = _refine_check(client, repository, timer, scenario, deck, cards)
        checks["refine_success"] = check
        result["refine"] = info
    else:
        checks["refine_success"] = Check(None)

    result.update({
        "title": deck.get("title"),
        "commander": deck.get("commander"),
        "colors": deck.get("colors"),
        "lands": lands,
        "main": main_total,
        "sideboard": _total(deck.get("sideboard", [])),
        "deck_id": deck.get("deck_id"),
        "checks": {k: asdict(v) for k, v in checks.items()},
    })
    return result


# ---------------------------------------------------------------------------
# Aggregation and reporting
# ---------------------------------------------------------------------------

def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int(round(pct / 100 * len(ordered) + 0.5)) - 1))
    return round(ordered[rank], 1)


def _rates(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for metric in METRICS:
        applicable = [r for r in results if r["checks"].get(metric, {}).get("ok") is not None]
        failed = [r for r in applicable if not r["checks"][metric]["ok"]]
        out[metric] = {
            "n": len(applicable),
            "passed": len(applicable) - len(failed),
            "rate": round((len(applicable) - len(failed)) / len(applicable), 4) if applicable else None,
            "failures": [{"id": r["id"], "detail": r["checks"][metric]["detail"]} for r in failed],
        }
    return out


def aggregate(results: list[dict[str, Any]], timer: Timer) -> dict[str, Any]:
    by_format = {fmt: _rates([r for r in results if r["format"] == fmt]) for fmt in ALL_FORMATS}
    by_group = {g: _rates([r for r in results if r["group"] == g]) for g in ("constructed", "commander", "prompt")}
    latency = {
        endpoint: {"n": len(samples), "p50_ms": _percentile(samples, 50), "p95_ms": _percentile(samples, 95),
                   "max_ms": round(max(samples), 1)}
        for endpoint, samples in sorted(timer.samples.items())
    }
    return {"overall": _rates(results), "by_format": by_format, "by_group": by_group, "latency": latency}


def run_benchmark(client: Any, repository: Any, scenarios: list[Scenario]) -> dict[str, Any]:
    timer = Timer()
    results = [run_scenario(client, repository, s, timer) for s in scenarios]
    return {"results": results, "summary": aggregate(results, timer)}


def _pct(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate * 100:.1f}%"


def render_markdown(report: dict[str, Any], *, cap: int = 12) -> str:
    meta = report["meta"]
    summary = report["summary"]
    overall = summary["overall"]
    lines = [
        "# Deck-generation benchmark",
        "",
        "Deterministic, LLM-free run of `qa/benchmark.py` (see `qa/README.md`).",
        "",
        f"- Run at: `{meta['run_at']}`",
        f"- Git commit: `{meta['git_commit']}`",
        f"- Database: {meta['database_label']} ({meta['card_count']} cards, {meta['archetype_count']} archetypes, "
        f"card data as of {meta['card_data_as_of']})",
        f"- Scenarios: {meta['scenario_count']} ({meta['group_counts']}); wall time {meta['wall_seconds']} s",
        "",
        "## Pass rates",
        "",
        "| Metric | Pass rate | Passed / applicable | What it checks |",
        "|---|---|---|---|",
    ]
    for metric in METRICS:
        m = overall[metric]
        lines.append(f"| {metric} | {_pct(m['rate'])} | {m['passed']} / {m['n']} | {METRIC_HELP[metric]} |")
    lines += ["", "## By format", "", "| Metric | " + " | ".join(ALL_FORMATS) + " |",
              "|---|" + "---|" * len(ALL_FORMATS)]
    for metric in METRICS:
        cells = []
        for fmt in ALL_FORMATS:
            m = summary["by_format"][fmt][metric]
            cells.append("n/a" if m["rate"] is None else f"{m['rate'] * 100:.0f}% ({m['passed']}/{m['n']})")
        lines.append(f"| {metric} | " + " | ".join(cells) + " |")
    lines += ["", "## Latency (in-process TestClient)", "", "| Endpoint | Calls | p50 ms | p95 ms | max ms |",
              "|---|---|---|---|---|"]
    for endpoint, lat in summary["latency"].items():
        lines.append(f"| {endpoint} | {lat['n']} | {lat['p50_ms']} | {lat['p95_ms']} | {lat['max_ms']} |")
    lines += ["", "## Failures", ""]
    any_fail = False
    for metric in METRICS:
        fails = overall[metric]["failures"]
        if not fails:
            continue
        any_fail = True
        lines.append(f"### {metric} ({len(fails)} failing)")
        lines.append("")
        for f in fails[:cap]:
            detail = f["detail"].replace("|", "/") if f["detail"] else ""
            lines.append(f"- `{f['id']}`" + (f": {detail}" if detail else ""))
        if len(fails) > cap:
            lines.append(f"- ... and {len(fails) - cap} more (see `qa/artifacts/benchmark.json`)")
        lines.append("")
    if not any_fail:
        lines.append("None.")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def _prepare_database(database_url: str | None) -> tuple[str, str]:
    """Return (DATABASE_URL, human label). Never hands out a path under var/."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="mtg-benchmark-db-"))
    if not database_url:
        db_path = tmp_dir / "cards.db"
        with gzip.open(FIXTURE_DB, "rb") as src, open(db_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return f"sqlite:///{db_path}", "fixture `api/tests/fixtures/cards.db.gz` (temp copy)"
    if database_url.startswith("sqlite:///"):
        path = Path(database_url[len("sqlite:///"):]).expanduser().resolve()
        if (ROOT / "var") in path.parents:
            copy = tmp_dir / path.name
            shutil.copyfile(path, copy)
            return f"sqlite:///{copy}", f"temp copy of `{path}`"
        return f"sqlite:///{path}", f"`{path}`"
    return database_url, f"`{database_url.split('@')[-1]}`"


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def disable_rate_limits() -> None:
    from app import rate_limiter

    rate_limiter.InMemoryRateLimiter.is_allowed = lambda self, key: True  # type: ignore[method-assign]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database-url", help="SQLAlchemy URL (default: decompressed test fixture). "
                        "SQLite files under var/ are copied to a temp dir first.")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON, help="per-scenario JSON output")
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY, help="Markdown summary output")
    parser.add_argument("--limit", type=int, help="run only the first N scenarios")
    parser.add_argument("--gate", action="store_true", help="run only the CI-gate subset")
    parser.add_argument("--db-label", help="how to name the DB in the summary (default: its path)")
    args = parser.parse_args(argv)

    # LLM-free and auth-free: set before app.config loads .env (override=False).
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MTG_API_KEY", "MTG_USE_OPTIMIZER_DEFAULT"):
        os.environ[key] = ""
    database_url, label = _prepare_database(args.database_url)
    label = args.db_label or label
    os.environ["DATABASE_URL"] = database_url
    if str(API_DIR) not in sys.path:
        sys.path.insert(0, str(API_DIR))

    import logging

    from fastapi.testclient import TestClient

    from app.main import app, repository

    logging.getLogger().setLevel(logging.WARNING)
    repository.refresh_service = None  # no background Scryfall refreshes
    disable_rate_limits()

    scenarios = gate_scenarios() if args.gate else generate_scenarios()
    if args.limit:
        scenarios = scenarios[: args.limit]
    client = TestClient(app)
    status = client.get("/api/data-status").json()

    started = time.perf_counter()
    report = run_benchmark(client, repository, scenarios)
    groups: dict[str, int] = {}
    for s in scenarios:
        groups[s.group] = groups.get(s.group, 0) + 1
    report["meta"] = {
        "run_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "git_commit": _git_commit(),
        "database_label": label,
        "card_count": status.get("card_count"),
        "archetype_count": status.get("archetype_count"),
        "card_data_as_of": status.get("card_data_as_of"),
        "scenario_count": len(scenarios),
        "group_counts": ", ".join(f"{k} {v}" for k, v in groups.items()),
        "wall_seconds": round(time.perf_counter() - started, 1),
    }
    report = {"meta": report["meta"], "summary": report["summary"], "results": report["results"]}

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, default=str))
    args.summary.write_text(render_markdown(report) + "\n")

    overall = report["summary"]["overall"]
    print(f"{len(scenarios)} scenarios on {label} in {report['meta']['wall_seconds']} s")
    for metric in METRICS:
        m = overall[metric]
        print(f"  {metric:24s} {_pct(m['rate']):>7s}  ({m['passed']}/{m['n']})")
    for endpoint, lat in report["summary"]["latency"].items():
        print(f"  latency {endpoint:16s} p50 {lat['p50_ms']} ms  p95 {lat['p95_ms']} ms")
    print(f"wrote {args.json} and {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
