"use client";

import { useEffect, useState } from "react";

import { DeckDiffView } from "./deck-diff-view";
import type { DeckRevision } from "@/hooks/use-deck-generator";
import { cardCount, diffCardLists } from "@/lib/deck-diff";

type Props = {
  revisions: DeckRevision[];
  loading: boolean;
  onUndo: () => void;
  onRestore: (id: number) => void;
};

function timeLabel(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** The in-memory revision stack: undo, compare any revision with the current one, restore. */
export function RevisionHistory({ revisions, loading, onUndo, onRestore }: Props) {
  const [compareId, setCompareId] = useState<number | null>(null);
  const current = revisions[revisions.length - 1];

  // A compare against a revision that fell off the stack (or the new current) is meaningless.
  useEffect(() => {
    if (compareId !== null && (!revisions.some((revision) => revision.id === compareId) || current?.id === compareId)) {
      setCompareId(null);
    }
  }, [revisions, compareId, current]);

  if (revisions.length < 2 || !current) return null;
  const compared = revisions.find((revision) => revision.id === compareId) ?? null;

  return (
    <section className="panel results-card" aria-labelledby="revision-history-heading">
      <div className="panel-heading-row">
        <h3 id="revision-history-heading" className="label">Revision history</h3>
        <button type="button" className="chip" onClick={onUndo} disabled={loading}>
          Undo last change
        </button>
      </div>
      <ol className="card-list revision-list" reversed>
        {[...revisions].reverse().map((revision) => {
          const isCurrent = revision.id === current.id;
          return (
            <li key={revision.id} className={`card-row revision-row ${isCurrent ? "active" : ""}`}>
              <div className="revision-text">
                <span>{revision.label}</span>
                <span className="muted revision-meta">
                  {timeLabel(revision.createdAt)} · {cardCount(revision.deck.mainboard)} cards
                  {isCurrent ? " · current" : ""}
                </span>
              </div>
              {!isCurrent ? (
                <div className="revision-actions">
                  <button
                    type="button"
                    className={`chip ${compareId === revision.id ? "active" : ""}`}
                    aria-pressed={compareId === revision.id}
                    aria-label={`Compare "${revision.label}" with the current deck`}
                    onClick={() => setCompareId((id) => (id === revision.id ? null : revision.id))}
                  >
                    Compare
                  </button>
                  <button
                    type="button"
                    className="chip"
                    disabled={loading}
                    aria-label={`Restore "${revision.label}"`}
                    onClick={() => onRestore(revision.id)}
                  >
                    Restore
                  </button>
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
      {compared ? (
        <div className="revision-compare">
          <DeckDiffView
            diff={diffCardLists(compared.deck.mainboard, current.deck.mainboard)}
            title={`From "${compared.label}" to the current deck`}
          />
        </div>
      ) : null}
    </section>
  );
}
