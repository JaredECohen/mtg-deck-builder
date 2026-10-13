"use client";

import { useId, useState } from "react";

import { groupByType } from "@/lib/group-by-type";
import type { CardRef, CardTypeMap, DeckCardExplanation } from "@/lib/types";

export type NotesByCard = Map<string, DeckCardExplanation>;

export function notesByCard(notes: DeckCardExplanation[] | undefined): NotesByCard {
  const map: NotesByCard = new Map();
  for (const note of notes ?? []) if (note.reason && !map.has(note.name)) map.set(note.name, note);
  return map;
}

type RowProps = {
  card: CardRef;
  quantityLabel: string;
  note?: DeckCardExplanation;
  onOpen: (name: string) => void;
};

/** One card: name opens the card modal; a "Why?" toggle reveals the card's reason. */
export function DeckCardRow({ card, quantityLabel, note, onOpen }: RowProps) {
  const [open, setOpen] = useState(false);
  const reasonId = useId();
  return (
    <li className="card-row card-row-action deck-card-row">
      <div className="deck-card-main">
        <button type="button" className="card-button" onClick={() => onOpen(card.name)}>
          <span>{card.name}</span>
          <span className="muted">{quantityLabel}</span>
        </button>
        {note ? (
          <button
            type="button"
            className="why-toggle"
            aria-expanded={open}
            aria-controls={reasonId}
            aria-label={`Why ${card.name}?`}
            onClick={() => setOpen((value) => !value)}
          >
            Why?
          </button>
        ) : null}
      </div>
      {note ? (
        <p id={reasonId} className="card-reason" hidden={!open}>
          {note.role ? <span className="card-reason-role">{note.role}</span> : null}
          {note.reason}
        </p>
      ) : null}
    </li>
  );
}

export function GroupedDeckList({
  cards,
  typeMap,
  emptyLabel,
  suffix,
  notes,
  onOpenCard
}: {
  cards: CardRef[];
  typeMap: CardTypeMap | undefined;
  emptyLabel?: string;
  suffix: string;
  notes?: NotesByCard;
  onOpenCard: (name: string) => void;
}) {
  const sections = groupByType(cards, typeMap);
  if (!sections.length) {
    return emptyLabel ? <p className="muted" style={{ marginTop: 4 }}>{emptyLabel}</p> : null;
  }
  return (
    <div className="deck-type-sections">
      {sections.map((section) => (
        <div key={`${suffix}-${section.type}`} className="deck-type-section">
          <div className="deck-type-heading">
            <span>{section.label}</span>
            <span className="muted">{section.count}</span>
          </div>
          <ul className="card-list">
            {section.cards.map((card) => (
              <DeckCardRow
                key={`${suffix}-${section.type}-${card.name}`}
                card={card}
                quantityLabel={`${card.quantity}x`}
                note={notes?.get(card.name)}
                onOpen={onOpenCard}
              />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
