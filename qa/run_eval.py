from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
SCENARIO_PATH = ROOT / "qa" / "deck_scenarios.json"
OUTPUT_DIR = ROOT / "qa" / "artifacts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_PATH = ROOT / "qa" / "REPORT.md"
DEFAULT_API_BASE = os.getenv("MTG_API_BASE")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_EVAL_MODEL", "gpt-4.1-mini")
OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "45"))
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "2"))
LLM_BATCH_SIZE = int(os.getenv("OPENAI_BATCH_SIZE", "5"))


def load_scenarios() -> list[dict[str, Any]]:
    return json.loads(SCENARIO_PATH.read_text())


def detect_api_base() -> str:
    candidates = [candidate for candidate in [DEFAULT_API_BASE, "http://127.0.0.1:8010", "http://127.0.0.1:8000"] if candidate]
    with httpx.Client(timeout=5.0) as client:
        for base in candidates:
            try:
                response = client.get(f"{base}/api/health")
                if response.status_code == 200 and response.json().get("status") == "ok":
                    return base
            except Exception:  # noqa: BLE001
                continue
    raise RuntimeError("Could not find a healthy MTG backend on the configured local ports.")


def build_local_client() -> TestClient:
    api_root = ROOT / "api"
    if str(api_root) not in sys.path:
        sys.path.append(str(api_root))
    from app.main import app

    return TestClient(app)


def _normalize_text(parts: list[str]) -> str:
    return " ".join(part.lower() for part in parts if part)


def _role_snapshot(role_summary: list[dict[str, Any]]) -> dict[str, int]:
    return {item["role"].lower(): int(item["total_cards"]) for item in role_summary}


def _matching_expectation_count(expectations: list[str], haystacks: list[str]) -> int:
    if not expectations:
        return 0
    search_blob = _normalize_text(haystacks)
    return sum(1 for item in expectations if item.lower() in search_blob)


def _score_from_ratio(matches: int, total: int, floor: int = 45, ceiling: int = 100) -> int:
    if total <= 0:
        return ceiling
    ratio = matches / total
    return max(floor, min(ceiling, round(floor + (ceiling - floor) * ratio)))


def heuristic_analysis(scenario: dict[str, Any], deck: dict[str, Any]) -> dict[str, Any]:
    expectations = scenario.get("expectations", {})
    request = scenario["request"]
    mainboard = deck["mainboard"]
    sideboard = deck["sideboard"]
    mechanics = deck.get("mechanics", [])
    role_summary = deck.get("role_summary", [])
    warnings = deck.get("warnings", [])
    score = deck["score"]
    main_count = sum(card["quantity"] for card in mainboard)
    issues: list[str] = []
    strengths: list[str] = []

    if not deck["is_legal"]:
        issues.append("Deck failed backend legality validation.")
    if deck["format"] != "commander" and main_count != 60:
        issues.append(f"Constructed deck has {main_count} cards instead of 60.")
    if deck["format"] == "commander" and main_count != 99:
        issues.append(f"Commander mainboard has {main_count} cards instead of 99.")
    if deck["format"] != "commander" and sum(card["quantity"] for card in sideboard) not in {0, 15}:
        issues.append("Constructed sideboard does not have 15 cards.")
    if score["mana"] < 70:
        issues.append("Mana score is weak.")
    if score["synergy"] < 70:
        issues.append("Synergy score is weak.")
    if score["role_balance"] < 70:
        issues.append("Role balance score is weak.")
    if not mechanics:
        issues.append("No key mechanics were surfaced in the explanation payload.")
    if len(role_summary) < 3:
        issues.append("Role summary is too shallow.")

    selected_archetype = deck.get("selected_archetype") or {}
    selected_metadata = selected_archetype.get("metadata") or {}
    explanation = deck.get("explanation", [])
    sections = deck.get("sections", [])
    section_titles = [section.get("title", "") for section in sections]
    section_summaries = [section.get("summary", "") for section in sections]
    section_bullets = [" ".join(section.get("bullets", [])) for section in sections]
    mechanic_labels = [item["label"] for item in mechanics]
    role_snapshot = _role_snapshot(role_summary)

    archetype_signals = [
        deck.get("strategy_summary", ""),
        selected_archetype.get("name", ""),
        " ".join(selected_archetype.get("tags", [])),
        " ".join(deck.get("source_archetypes", [])),
        " ".join(explanation),
        " ".join(section_titles + section_summaries + section_bullets),
        " ".join(mechanic_labels),
    ]
    expected_tags = expectations.get("archetype_tags", [])
    expected_mechanics = expectations.get("mechanic_tags", [])
    archetype_matches = _matching_expectation_count(expected_tags + expected_mechanics, archetype_signals)
    archetype_match_quality = _score_from_ratio(archetype_matches, len(expected_tags) + len(expected_mechanics))

    if expected_tags and archetype_matches == 0:
        issues.append("Retrieved shell does not clearly match the expected archetype/theme.")
    else:
        strengths.append(f"Archetype match score: {archetype_match_quality}.")

    expected_roles = expectations.get("required_roles", [])
    role_matches = sum(1 for role in expected_roles if role.lower() in role_snapshot)
    package_signals = int(any(title == "Retrieved Packages" for title in section_titles))
    package_signals += int(bool(selected_metadata.get("core_cards")))
    package_signals += int(bool(selected_metadata.get("flex_cards")))
    package_signals += int(bool(selected_metadata.get("land_packages")))
    if deck["format"] == "commander":
        package_signals += int(selected_metadata.get("commander_package") is not None)
    package_coherence = min(100, 45 + role_matches * 12 + package_signals * 8 + min(score["role_balance"], 100) // 4)
    if package_coherence < 70:
        issues.append("Package structure looks shallow for the requested shell.")
    else:
        strengths.append(f"Package coherence score: {package_coherence}.")

    recognizable_shell = min(
        100,
        40
        + int(bool(deck.get("source_archetypes"))) * 15
        + int(bool(selected_archetype.get("source_count"))) * 10
        + int(any("retrieved" in item.lower() for item in explanation)) * 15
        + int("Retrieved Packages" in section_titles) * 10
        + min(archetype_match_quality, 100) // 4,
    )
    if recognizable_shell < 70:
        issues.append("Deck does not yet read like a recognizable retrieved shell.")
    else:
        strengths.append(f"Recognizable shell score: {recognizable_shell}.")

    commander_plausibility = 100
    if deck["format"] == "commander":
        commander_card = deck.get("commander")
        requested_colors = set(request.get("colors", []))
        commander_colors = set((request.get("colors") or []) if not selected_archetype.get("commander") else selected_archetype.get("colors", []))
        expected_commander_tags = expectations.get("commander_tags", [])
        commander_matches = _matching_expectation_count(
            expected_commander_tags,
            [commander_card or "", " ".join(selected_archetype.get("tags", [])), " ".join(explanation), " ".join(mechanic_labels)],
        )
        commander_plausibility = 45
        commander_plausibility += int(bool(commander_card)) * 15
        commander_plausibility += int(bool(selected_metadata.get("commander_package"))) * 15
        commander_plausibility += int(any(title == "Commander Choice" for title in section_titles)) * 10
        commander_plausibility += _score_from_ratio(commander_matches, len(expected_commander_tags), floor=0, ceiling=15)
        if requested_colors and commander_colors:
            commander_plausibility += 10 if requested_colors.issubset(commander_colors) else 0
        commander_plausibility = min(100, commander_plausibility)
        if commander_plausibility < 70:
            issues.append("Commander choice is not yet well-supported by the retrieved corpus and explanation.")
        else:
            strengths.append(f"Commander plausibility score: {commander_plausibility}.")

    if not warnings:
        strengths.append("Backend did not find any structural warnings.")
    if mechanics:
        strengths.append(f"Mechanics exposed: {', '.join(item['label'] for item in mechanics[:3])}.")
    if role_summary:
        snapshot = ", ".join(f"{item['role']} {item['total_cards']}" for item in role_summary[:4])
        strengths.append(f"Role coverage: {snapshot}.")
    if sections:
        strengths.append("Deck includes structured explanation sections.")

    retrieval_issues = [issue for issue in issues if "Retrieved shell" in issue or "Package structure" in issue or "recognizable retrieved shell" in issue]
    legality_issues = [issue for issue in issues if "legal" in issue.lower() or "cards instead of" in issue.lower() or "sideboard" in issue.lower()]
    commander_issues = [issue for issue in issues if "Commander" in issue]

    verdict = "strong"
    if legality_issues or score["total"] < 80:
        verdict = "weak"
    elif retrieval_issues or commander_issues or len(issues) > 2:
        verdict = "mixed"

    return {
        "verdict": verdict,
        "strengths": strengths,
        "issues": issues + warnings[:4],
        "score_snapshot": score,
        "dimension_scores": {
            "archetype_match_quality": archetype_match_quality,
            "package_coherence": package_coherence,
            "recognizable_shell": recognizable_shell,
            "commander_plausibility": commander_plausibility,
        },
        "issue_buckets": {
            "legality": legality_issues,
            "retrieval": retrieval_issues,
            "commander": commander_issues,
        },
    }


def _extract_output_text(body: dict[str, Any]) -> str:
    if body.get("status") == "incomplete":
        reason = (body.get("incomplete_details") or {}).get("reason", "unknown")
        raise ValueError(f"OpenAI response incomplete: {reason}")
    output_text = body.get("output_text")
    if output_text:
        return output_text
    for item in body.get("output", []):
        for content in item.get("content", []):
            if isinstance(content, dict) and "text" in content:
                return str(content["text"])
    raise ValueError("Responses API did not return extractable text content")


def _post_openai(payload: dict[str, Any]) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    last_error: Exception | None = None
    for attempt in range(OPENAI_MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=OPENAI_TIMEOUT_SECONDS) as client:
                response = client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
                response.raise_for_status()
                return response.json()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < OPENAI_MAX_RETRIES:
                time.sleep(min(2 * (attempt + 1), 5))
    raise RuntimeError(str(last_error) if last_error else "Unknown OpenAI error")


def _compact_deck_for_llm(deck: dict[str, Any]) -> dict[str, Any]:
    mainboard = deck["mainboard"]
    nonlands = [card for card in mainboard if card["name"] not in {"Plains", "Island", "Swamp", "Mountain", "Forest"}]
    return {
        "title": deck["title"],
        "format": deck["format"],
        "colors": deck["colors"],
        "commander": deck.get("commander"),
        "score": deck["score"],
        "warnings": deck.get("warnings", [])[:5],
        "validation_errors": deck.get("validation_errors", [])[:5],
        "strategy_summary": deck.get("strategy_summary"),
        "explanation": deck.get("explanation", [])[:4],
        "mechanics": deck.get("mechanics", [])[:3],
        "role_summary": deck.get("role_summary", [])[:5],
        "selected_archetype": {
            "name": (deck.get("selected_archetype") or {}).get("name"),
            "tags": (deck.get("selected_archetype") or {}).get("tags", [])[:5],
            "source_count": (deck.get("selected_archetype") or {}).get("source_count"),
        },
        "mainboard_sample": nonlands[:12],
        "sideboard_sample": deck["sideboard"][:8],
    }


def llm_analysis_batch(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not OPENAI_API_KEY:
        return {
            item["scenario_id"]: {"status": "skipped", "reason": "OPENAI_API_KEY not set"}
            for item in items
        }

    evaluations: dict[str, dict[str, Any]] = {}
    for start in range(0, len(items), LLM_BATCH_SIZE):
        batch = items[start:start + LLM_BATCH_SIZE]
        prompt = {
            "task": "Judge whether each MTG deck output is sensible and resembles a recognizable shell. Return JSON only.",
            "criteria": [
                "legality",
                "coherent game plan",
                "mana plausibility",
                "role coverage",
                "synergy plausibility",
                "retrieval/archetype match quality",
                "commander plausibility when relevant",
                "whether explanation matches the list",
                "whether obvious nonsense appears",
            ],
            "scenarios": [
                {
                    "scenario_id": item["scenario_id"],
                    "expectations": item["expectations"],
                    "heuristic": {
                        "verdict": item["heuristic"]["verdict"],
                        "dimension_scores": item["heuristic"]["dimension_scores"],
                        "issues": item["heuristic"]["issues"][:4],
                    },
                    "deck": _compact_deck_for_llm(item["deck"]),
                }
                for item in batch
            ],
        }
        payload = {
            "model": OPENAI_MODEL,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {"type": "input_text", "text": "You are a strict MTG deckbuilding evaluator. Return concise JSON only."}
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps(prompt)}],
                },
            ],
            "max_output_tokens": 4000,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "deck_eval_batch",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "evaluations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "scenario_id": {"type": "string"},
                                        "verdict": {"type": "string"},
                                        "summary": {"type": "string"},
                                        "strengths": {"type": "array", "items": {"type": "string"}},
                                        "issues": {"type": "array", "items": {"type": "string"}},
                                        "retrieval_assessment": {"type": "string"},
                                        "commander_assessment": {"type": "string"},
                                    },
                                    "required": [
                                        "scenario_id",
                                        "verdict",
                                        "summary",
                                        "strengths",
                                        "issues",
                                        "retrieval_assessment",
                                        "commander_assessment",
                                    ],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["evaluations"],
                        "additionalProperties": False,
                    },
                },
            },
        }
        if OPENAI_MODEL.startswith("gpt-5"):
            payload["reasoning"] = {"effort": "low"}
            payload["text"]["verbosity"] = "low"

        try:
            body = _post_openai(payload)
            parsed = json.loads(_extract_output_text(body))
            for evaluation in parsed.get("evaluations", []):
                evaluation["status"] = "completed"
                evaluations[evaluation["scenario_id"]] = evaluation
        except Exception as exc:  # noqa: BLE001
            failure = {"status": "failed", "reason": str(exc)}
            for item in batch:
                evaluations[item["scenario_id"]] = failure

    return evaluations


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts = Counter(result["heuristic"]["verdict"] for result in results)
    llm_statuses = Counter(result["llm"].get("status", "unknown") for result in results)
    retrieval_failures = [result["scenario_id"] for result in results if result["heuristic"]["issue_buckets"]["retrieval"]]
    commander_failures = [result["scenario_id"] for result in results if result["heuristic"]["issue_buckets"]["commander"]]
    legality_failures = [result["scenario_id"] for result in results if result["heuristic"]["issue_buckets"]["legality"]]
    averages: dict[str, int] = {}
    for dimension in ("archetype_match_quality", "package_coherence", "recognizable_shell", "commander_plausibility"):
        values = [result["heuristic"]["dimension_scores"][dimension] for result in results]
        averages[dimension] = round(sum(values) / len(values)) if values else 0
    return {
        "total_scenarios": len(results),
        "heuristic_verdicts": dict(verdicts),
        "llm_statuses": dict(llm_statuses),
        "dimension_averages": averages,
        "retrieval_failures": retrieval_failures,
        "commander_failures": commander_failures,
        "legality_failures": legality_failures,
        "weak_or_mixed_scenarios": [result["scenario_id"] for result in results if result["heuristic"]["verdict"] != "strong"],
    }


def write_markdown_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# MTG Deck Builder QA Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- API base: `{report['api_base']}`",
        "",
        "## Summary",
        "",
        f"- Scenario count: `{summary['total_scenarios']}`",
        f"- Heuristic verdicts: `{summary['heuristic_verdicts']}`",
        f"- LLM statuses: `{summary['llm_statuses']}`",
        f"- Dimension averages: `{summary['dimension_averages']}`",
        f"- Retrieval failures: `{summary['retrieval_failures']}`",
        f"- Commander failures: `{summary['commander_failures']}`",
        f"- Legality failures: `{summary['legality_failures']}`",
        "",
        "## Scenario Results",
        "",
    ]
    for result in report["results"]:
        dims = result["heuristic"]["dimension_scores"]
        llm = result["llm"]
        lines.extend(
            [
                f"### {result['scenario_id']}",
                "",
                f"- Verdict: `{result['heuristic']['verdict']}`",
                f"- Dimension scores: `{dims}`",
                f"- LLM status: `{llm.get('status', 'unknown')}`",
                f"- LLM verdict: `{llm.get('verdict', '-')}`",
                f"- Retrieval issues: `{result['heuristic']['issue_buckets']['retrieval']}`",
                f"- Commander issues: `{result['heuristic']['issue_buckets']['commander']}`",
                f"- Main issues: `{result['heuristic']['issues'][:4]}`",
                "",
            ]
        )
    REPORT_PATH.write_text("\n".join(lines) + "\n")


def _generate_results_with_http_client(scenarios: list[dict[str, Any]], api_base: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with httpx.Client(timeout=60.0) as client:
        health = client.get(f"{api_base}/api/health")
        health.raise_for_status()
        for scenario in scenarios:
            response = client.post(f"{api_base}/v1/decks/generate", json=scenario["request"])
            response.raise_for_status()
            deck = response.json()
            heuristic = heuristic_analysis(scenario, deck)
            results.append(
                {
                    "scenario_id": scenario["id"],
                    "request": scenario["request"],
                    "expectations": scenario.get("expectations", {}),
                    "deck": deck,
                    "heuristic": heuristic,
                }
            )
    return results


def _generate_results_with_test_client(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with build_local_client() as client:
        health = client.get("/api/health")
        health.raise_for_status()
        for scenario in scenarios:
            response = client.post("/v1/decks/generate", json=scenario["request"])
            response.raise_for_status()
            deck = response.json()
            heuristic = heuristic_analysis(scenario, deck)
            results.append(
                {
                    "scenario_id": scenario["id"],
                    "request": scenario["request"],
                    "expectations": scenario.get("expectations", {}),
                    "deck": deck,
                    "heuristic": heuristic,
                }
            )
    return results


def main() -> None:
    scenarios = load_scenarios()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    api_base: str

    try:
        api_base = detect_api_base()
        results = _generate_results_with_http_client(scenarios, api_base)
    except RuntimeError:
        api_base = "inprocess:testclient"
        results = _generate_results_with_test_client(scenarios)

    llm_by_scenario = llm_analysis_batch(results)
    for result in results:
        result["llm"] = llm_by_scenario.get(result["scenario_id"], {"status": "failed", "reason": "missing llm result"})

    summary = summarize(results)
    report = {
        "generated_at": timestamp,
        "api_base": api_base,
        "summary": summary,
        "results": results,
    }
    out_path = OUTPUT_DIR / f"deck_eval_{timestamp}.json"
    out_path.write_text(json.dumps(report, indent=2))
    (OUTPUT_DIR / "latest_report.json").write_text(json.dumps(report, indent=2))
    write_markdown_report(report)
    print(json.dumps({"report": str(out_path), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
