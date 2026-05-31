"use client";

import { useSimValidation } from "@/hooks/use-sim-validation";
import type { DeckProvenance, DeckResponse } from "@/lib/types";

type Props = {
  provenance: DeckProvenance;
  commanderRequested?: boolean;
  /** Current deck — needed to build a swapped DeckResponse from optimizer output. */
  currentDeck?: DeckResponse | null;
  /** Called when the user accepts the optimizer's improved deck. */
  onApplyOptimized?: (next: DeckResponse) => void;
};

const SOURCE_LABEL: Record<DeckProvenance["source_type"], { label: string; description: string; tone: "good" | "warn" | "neutral" }> = {
  corpus: {
    label: "Corpus-backed",
    description: "Built from real archetype shells in the corpus.",
    tone: "good"
  },
  hybrid: {
    label: "Hybrid",
    description: "Started from a corpus shell; most slots filled by deterministic rules.",
    tone: "neutral"
  },
  fallback: {
    label: "Fallback",
    description: "No corpus shell matched. Built from card pool by color and role rules.",
    tone: "warn"
  },
  builtin: {
    label: "Built-in seed",
    description: "Format has no corpus archetypes — assembled from a curated built-in template.",
    tone: "neutral"
  }
};

function confidenceTone(confidence: number): "good" | "warn" | "neutral" {
  if (confidence >= 0.7) return "good";
  if (confidence >= 0.4) return "neutral";
  return "warn";
}

/** Convert optimizer's flat singleton card list into DeckResponse mainboard
 * format ([{name, quantity}]). Same-name cards aggregate. */
function optimizerToMainboard(cards: { name: string }[]): { name: string; quantity: number }[] {
  const counts = new Map<string, number>();
  for (const c of cards) {
    counts.set(c.name, (counts.get(c.name) ?? 0) + 1);
  }
  return Array.from(counts.entries()).map(([name, quantity]) => ({ name, quantity }));
}

export function ProvenanceBanner({ provenance, commanderRequested, currentDeck, onApplyOptimized }: Props) {
  const meta = SOURCE_LABEL[provenance.source_type];
  const tone = confidenceTone(provenance.confidence);
  const sim = useSimValidation(provenance.sim_validation_job_id ?? null);
  // Only surface the Apply button when the simulator actually found a
  // meaningfully-better deck — defined as ≥10% improvement over the seed's
  // fitness score. Without this gate, we'd offer a "swap" that doesn't
  // make the deck appreciably better, which would erode trust in the
  // feature.
  const IMPROVEMENT_THRESHOLD = 0.10;
  const hasImprovement =
    sim.improvement != null && sim.improvement >= IMPROVEMENT_THRESHOLD;
  const canApply =
    sim.status === "succeeded" &&
    sim.optimizedDeck &&
    sim.optimizedDeck.length > 0 &&
    hasImprovement &&
    currentDeck &&
    onApplyOptimized;

  function handleApply() {
    if (!sim.optimizedDeck || !currentDeck || !onApplyOptimized) return;
    const newMain = optimizerToMainboard(sim.optimizedDeck);
    onApplyOptimized({
      ...currentDeck,
      mainboard: newMain,
      // Mark this deck as sim-optimized in the provenance notes so the
      // user sees what changed; clear the job id to avoid re-polling.
      provenance: {
        ...currentDeck.provenance,
        notes: [...currentDeck.provenance.notes, "Replaced mainboard with simulator-optimized version."],
        sim_validation_job_id: null,
      },
    });
  }

  return (
    <div className="provenance-card">
      <div className="provenance-row">
        <span className={`status-pill ${meta.tone === "good" ? "good" : meta.tone === "warn" ? "bad" : ""}`}>
          {meta.label}
        </span>
        <span className={`status-pill ${tone === "good" ? "good" : tone === "warn" ? "bad" : ""}`} title="Generator confidence">
          Confidence {Math.round(provenance.confidence * 100)}%
        </span>
        {provenance.sim_validation_job_id ? (
          <span
            className={`status-pill ${sim.status === "succeeded" ? "good" : sim.status === "failed" ? "bad" : ""}`}
            title="Background simulator validation"
          >
            {sim.status === "running"
              ? "Validating with simulator…"
              : sim.status === "succeeded"
                ? "Validated by simulator"
                : sim.status === "failed"
                  ? "Sim validation failed"
                  : "Sim validation queued"}
          </span>
        ) : null}
        <span className="muted">Evidence decks: {provenance.evidence_count}</span>
      </div>
      <p className="muted" style={{ marginTop: 8 }}>{meta.description}</p>
      {provenance.retrieved_from.length ? (
        <p className="muted" style={{ marginTop: 4 }}>
          Retrieved shells: {provenance.retrieved_from.slice(0, 3).join(", ")}
        </p>
      ) : (
        <p className="muted" style={{ marginTop: 4 }}>
          No retrieved shells {commanderRequested ? "for this commander." : "for these constraints."}
        </p>
      )}
      {canApply ? (
        <div style={{ marginTop: 12 }}>
          <button type="button" className="button secondary" onClick={handleApply} style={{ fontSize: 13, padding: "6px 14px" }}>
            Apply sim-optimized version
          </button>
          <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>
            Simulator improved fitness by {sim.improvement != null ? `${Math.round(sim.improvement * 100)}%` : "—"}
            {sim.baselineScore != null && sim.optimizerScore != null
              ? ` (${sim.baselineScore.toFixed(2)} → ${sim.optimizerScore.toFixed(2)})`
              : ""}
            . Swap it in to replace the current mainboard.
          </span>
        </div>
      ) : sim.status === "succeeded" && sim.optimizedDeck && sim.optimizedDeck.length > 0 && sim.improvement != null ? (
        <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>
          Simulator validated this deck. Improvement was only{" "}
          {Math.round(sim.improvement * 100)}% — below the {Math.round(IMPROVEMENT_THRESHOLD * 100)}% threshold to suggest a swap.
        </p>
      ) : null}
      {provenance.notes.length ? (
        <ul className="provenance-notes">
          {provenance.notes.map((note, index) => (
            <li key={`prov-note-${index}`}>{note}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
