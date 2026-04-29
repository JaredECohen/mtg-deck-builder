"use client";

import type { DeckProvenance } from "@/lib/types";

type Props = {
  provenance: DeckProvenance;
  commanderRequested?: boolean;
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
  }
};

function confidenceTone(confidence: number): "good" | "warn" | "neutral" {
  if (confidence >= 0.7) return "good";
  if (confidence >= 0.4) return "neutral";
  return "warn";
}

export function ProvenanceBanner({ provenance, commanderRequested }: Props) {
  const meta = SOURCE_LABEL[provenance.source_type];
  const tone = confidenceTone(provenance.confidence);
  return (
    <div className="provenance-card">
      <div className="provenance-row">
        <span className={`status-pill ${meta.tone === "good" ? "good" : meta.tone === "warn" ? "bad" : ""}`}>
          {meta.label}
        </span>
        <span className={`status-pill ${tone === "good" ? "good" : tone === "warn" ? "bad" : ""}`} title="Generator confidence">
          Confidence {Math.round(provenance.confidence * 100)}%
        </span>
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
