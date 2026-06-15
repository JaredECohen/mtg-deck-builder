"use client";

/**
 * DeckDiffView — visualizes a before/after decklist diff
 * (POST /v1/decks/diff). Used to show what the optimizer / refinement
 * changed relative to the starting list.
 */

import type { DeckDiffResult } from "@/lib/api";

export function DeckDiffView({ diff }: { diff: DeckDiffResult }) {
  if (diff.summary.identical) {
    return <p className="deck-diff-empty">No changes — the lists are identical.</p>;
  }
  return (
    <section aria-label="Deck changes" className="deck-diff">
      <header>
        <h3>Changes</h3>
        <p>
          +{diff.summary.cards_added} added · −{diff.summary.cards_removed} removed ·{" "}
          {diff.summary.total_changes} total
        </p>
      </header>
      <ul className="diff-list" style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {diff.added.map((e) => (
          <li key={`a-${e.name}`} style={{ color: "#16a34a" }}>+ {e.quantity} {e.name}</li>
        ))}
        {diff.increased.map((e) => (
          <li key={`i-${e.name}`} style={{ color: "#16a34a" }}>
            ↑ {e.name} {e.from} → {e.to}
          </li>
        ))}
        {diff.decreased.map((e) => (
          <li key={`d-${e.name}`} style={{ color: "#dc2626" }}>
            ↓ {e.name} {e.from} → {e.to}
          </li>
        ))}
        {diff.removed.map((e) => (
          <li key={`r-${e.name}`} style={{ color: "#dc2626" }}>− {e.quantity} {e.name}</li>
        ))}
      </ul>
    </section>
  );
}
