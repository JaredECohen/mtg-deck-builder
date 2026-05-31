"use client";

import type { SavedDeckSummary } from "@/lib/api";

type Props = {
  decks: SavedDeckSummary[];
  onLoad: (deckId: string) => void;
  onDelete: (deckId: string) => void;
};

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export function SavedDecksPanel({ decks, onLoad, onDelete }: Props) {
  if (decks.length === 0) {
    return (
      <div className="panel form-card">
        <span className="label">Saved Decks</span>
        <p className="muted" style={{ fontSize: 13 }}>
          No saved decks yet. Generate a deck and click <strong>Save deck</strong> on the result.
        </p>
      </div>
    );
  }
  return (
    <div className="panel form-card">
      <span className="label">Saved Decks ({decks.length})</span>
      <ul className="card-list" style={{ marginTop: 8 }}>
        {decks.map((deck) => (
          <li key={deck.id} className="card-row" style={{ alignItems: "flex-start", gap: 8 }}>
            <button type="button" className="card-button" onClick={() => onLoad(deck.id)} style={{ flex: 1, textAlign: "left" }}>
              <span>{deck.title}</span>
              <span className="muted" style={{ fontSize: 11 }}>
                {deck.format} • {formatDate(deck.created_at)}
              </span>
            </button>
            <button type="button" className="chip" onClick={() => onDelete(deck.id)} aria-label={`Delete ${deck.title}`}>
              ✕
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
