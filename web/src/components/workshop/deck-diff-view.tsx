"use client";

/**
 * DeckDiffView: a before/after decklist diff (refine `changes`, or a local
 * compare between two revisions).
 */

import type { DeckChanges, DeckDiffResult } from "@/lib/types";

type Props = {
  diff: DeckDiffResult | DeckChanges;
  title?: string;
};

export function DeckDiffView({ diff, title = "Changes" }: Props) {
  const sideboard = "sideboard" in diff ? diff.sideboard : undefined;
  const sideboardNote =
    sideboard && !sideboard.identical
      ? `Sideboard: +${sideboard.cards_added} / −${sideboard.cards_removed}.`
      : null;
  if (diff.summary.identical) {
    return (
      <section aria-label={title} className="deck-diff">
        <h3 className="label">{title}</h3>
        <p className="muted deck-diff-empty">No mainboard changes.{sideboardNote ? ` ${sideboardNote}` : ""}</p>
      </section>
    );
  }
  return (
    <section aria-label={title} className="deck-diff">
      <h3 className="label">{title}</h3>
      <p className="muted deck-diff-summary">
        +{diff.summary.cards_added} added · −{diff.summary.cards_removed} removed · {diff.summary.total_changes} total
        {sideboardNote ? ` · ${sideboardNote}` : ""}
      </p>
      <ul className="diff-list">
        {diff.added.map((entry) => (
          <li key={`a-${entry.name}`} className="diff-add">
            <span aria-hidden="true">+ </span>
            <span className="sr-only">Added </span>
            {entry.quantity} {entry.name}
          </li>
        ))}
        {diff.increased.map((entry) => (
          <li key={`i-${entry.name}`} className="diff-add">
            <span aria-hidden="true">↑ </span>
            <span className="sr-only">More copies of </span>
            {entry.name} {entry.from} → {entry.to}
          </li>
        ))}
        {diff.decreased.map((entry) => (
          <li key={`d-${entry.name}`} className="diff-remove">
            <span aria-hidden="true">↓ </span>
            <span className="sr-only">Fewer copies of </span>
            {entry.name} {entry.from} → {entry.to}
          </li>
        ))}
        {diff.removed.map((entry) => (
          <li key={`r-${entry.name}`} className="diff-remove">
            <span aria-hidden="true">− </span>
            <span className="sr-only">Removed </span>
            {entry.quantity} {entry.name}
          </li>
        ))}
      </ul>
    </section>
  );
}
