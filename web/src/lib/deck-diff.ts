import type { CardRef, DeckDiffResult } from "@/lib/types";

function counts(cards: CardRef[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const card of cards) map.set(card.name, (map.get(card.name) ?? 0) + card.quantity);
  return map;
}

/**
 * Client-side card diff with the same shape as POST /v1/decks/diff, so
 * comparing two local revisions needs no network round trip.
 */
export function diffCardLists(before: CardRef[], after: CardRef[]): DeckDiffResult {
  const a = counts(before);
  const b = counts(after);
  const diff: DeckDiffResult = {
    added: [],
    removed: [],
    increased: [],
    decreased: [],
    unchanged: [],
    summary: { cards_added: 0, cards_removed: 0, total_changes: 0, identical: true }
  };
  const names = [...new Set([...a.keys(), ...b.keys()])].sort((x, y) => x.localeCompare(y));
  for (const name of names) {
    const from = a.get(name) ?? 0;
    const to = b.get(name) ?? 0;
    if (from === to) diff.unchanged.push({ name, quantity: to });
    else if (from === 0) diff.added.push({ name, quantity: to });
    else if (to === 0) diff.removed.push({ name, quantity: from });
    else if (to > from) diff.increased.push({ name, from, to, delta: to - from });
    else diff.decreased.push({ name, from, to, delta: from - to });
    if (to > from) diff.summary.cards_added += to - from;
    if (from > to) diff.summary.cards_removed += from - to;
  }
  diff.summary.total_changes = diff.summary.cards_added + diff.summary.cards_removed;
  diff.summary.identical = diff.summary.total_changes === 0;
  return diff;
}

export function cardCount(cards: CardRef[]): number {
  return cards.reduce((sum, card) => sum + card.quantity, 0);
}
