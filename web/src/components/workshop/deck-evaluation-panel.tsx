"use client";

/**
 * DeckEvaluationPanel — renders the multi-signal deck-evaluation engine
 * output (POST /v1/decks/evaluate): win rate with confidence interval,
 * flood/screw resistance, interaction resilience, inevitability,
 * consistency, and the engine's qualitative notes.
 *
 * A `detailed` flag (driven by the beginner/expert mode toggle) controls
 * whether the full bar grid + raw notes are shown or just the headline.
 */

import type { DeckEvaluation } from "@/lib/api";

const METRICS: { key: keyof DeckEvaluation; label: string; help: string }[] = [
  { key: "flood_resistance", label: "Flood resistance", help: "Holds up on land-heavy keeps" },
  { key: "screw_resistance", label: "Screw resistance", help: "Functions on land-light keeps" },
  { key: "interaction_resilience", label: "Resilience", help: "Wins retained under disruption" },
  { key: "inevitability", label: "Inevitability", help: "Closes long games / card advantage" },
  { key: "consistency", label: "Consistency", help: "Low kill-turn variance" },
  { key: "card_advantage_density", label: "Card advantage", help: "Raw engine density" }
];

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function barColor(value: number): string {
  if (value >= 0.66) return "#16a34a";
  if (value >= 0.4) return "#d97706";
  return "#dc2626";
}

export function DeckEvaluationPanel({
  evaluation,
  detailed = true
}: {
  evaluation: DeckEvaluation;
  detailed?: boolean;
}) {
  const [ciLo, ciHi] = evaluation.win_rate_ci;
  return (
    <section aria-label="Deck evaluation" className="deck-evaluation">
      <header>
        <h3>Simulation verdict</h3>
        <p>
          <strong>{pct(evaluation.win_rate)}</strong> goldfish win rate{" "}
          <span title="Wilson 95% confidence interval">
            (95% CI {pct(ciLo)}–{pct(ciHi)})
          </span>{" "}
          · avg kill turn {evaluation.avg_kill_turn.toFixed(1)} ± {evaluation.kill_turn_stdev.toFixed(1)}{" "}
          · {evaluation.archetype} · {evaluation.games} games
        </p>
      </header>

      {detailed && (
        <ul className="metric-grid" style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {METRICS.map((metric) => {
            const value = Number(evaluation[metric.key] ?? 0);
            return (
              <li key={metric.key} style={{ marginBottom: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                  <span title={metric.help}>{metric.label}</span>
                  <span>{pct(value)}</span>
                </div>
                <div style={{ background: "#e5e7eb", borderRadius: 4, height: 8 }} role="meter"
                  aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}
                  aria-label={metric.label}>
                  <div style={{ width: pct(value), background: barColor(value), height: 8, borderRadius: 4 }} />
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {detailed && evaluation.notes.length > 0 && (
        <ul className="eval-notes">
          {evaluation.notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}

      {evaluation.unresolved_cards.length > 0 && (
        <p className="eval-warning">
          Skipped {evaluation.unresolved_cards.length} unrecognized card(s):{" "}
          {evaluation.unresolved_cards.join(", ")}
        </p>
      )}
    </section>
  );
}
