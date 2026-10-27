import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ManaCurveChart } from "@/components/workshop/mana-curve-chart";
import { groupByType } from "@/lib/group-by-type";
import { SITE_NAME } from "@/lib/blog";
import {
  COLOR_LABELS,
  cardTypeMap,
  deckBlurb,
  fetchPublicDeck,
  formatLabel,
  formatPrice,
  type PublicCardNote,
  type PublicDeck
} from "@/lib/public-deck";

type Params = { params: Promise<{ token: string }> };

export const dynamic = "force-dynamic";

function notesByName(notes: PublicCardNote[]): Map<string, PublicCardNote> {
  const map = new Map<string, PublicCardNote>();
  for (const note of notes) {
    if (note.reason && !map.has(note.name)) map.set(note.name, note);
  }
  return map;
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { token } = await params;
  const deck = await fetchPublicDeck(token);
  if (!deck) return { title: `Deck not found | ${SITE_NAME}`, robots: { index: false, follow: false } };
  const title = `${deck.name} — ${formatLabel(deck.format)} deck | ${SITE_NAME}`;
  const description = deckBlurb(deck);
  const indexable = deck.visibility !== "unlisted";
  return {
    title,
    description,
    alternates: { canonical: `/d/${deck.share_token}` },
    robots: indexable ? { index: true, follow: true } : { index: false, follow: false },
    openGraph: {
      type: "article",
      title: deck.name,
      description,
      url: `/d/${deck.share_token}`,
      siteName: SITE_NAME
    },
    twitter: {
      card: "summary_large_image",
      title: deck.name,
      description
    }
  };
}

function ColorPips({ colors }: { colors: string[] }) {
  const known = colors.filter((color) => color in COLOR_LABELS);
  if (!known.length) return <span className="muted">Colorless</span>;
  return (
    <span className="color-pips">
      {known.map((color) => (
        <span key={color} className={`color-pip pip-${color.toLowerCase()}`} title={COLOR_LABELS[color]}>
          <span className="sr-only">{COLOR_LABELS[color]}</span>
          <span aria-hidden="true">{color}</span>
        </span>
      ))}
    </span>
  );
}

function DeckSection({
  title,
  cards,
  deck,
  notes
}: {
  title: string;
  cards: PublicDeck["mainboard"];
  deck: PublicDeck;
  notes: Map<string, PublicCardNote>;
}) {
  const sections = groupByType(cards, cardTypeMap(deck.card_types));
  if (!sections.length) return null;
  return (
    <section className="share-zone">
      <h2>{title}</h2>
      {sections.map((section) => (
        <div key={section.type} className="deck-type-section">
          <div className="deck-type-heading">
            <span>{section.label}</span>
            <span className="muted">{section.count}</span>
          </div>
          <ul className="card-list">
            {section.cards.map((card) => {
              const note = notes.get(card.name);
              return (
                <li key={card.name} className="card-row share-card">
                  <div className="share-card-name">
                    <span>{card.name}</span>
                    <span className="muted">{card.quantity}×</span>
                  </div>
                  {note?.reason ? (
                    <p className="card-reason">
                      <span className="card-reason-role">Why?</span>
                      {note.role ? <span className="card-reason-role">{note.role}</span> : null}
                      {note.reason}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </section>
  );
}

export default async function SharedDeckPage({ params }: Params) {
  const { token } = await params;
  const deck = await fetchPublicDeck(token);
  if (!deck) notFound();
  const notes = notesByName(deck.card_notes);
  const price = formatPrice(deck.price_usd);
  const count = deck.mainboard.reduce((sum, card) => sum + card.quantity, 0);

  return (
    <main className="shell share-page">
      <p className="eyebrow">Shared deck</p>
      <h1>{deck.name}</h1>
      <p className="share-meta">
        <span>{formatLabel(deck.format)}</span>
        <ColorPips colors={deck.colors} />
        <span>{count} cards</span>
        {price ? <span>{price}</span> : null}
        {deck.commander ? <span>Commander: {deck.commander}</span> : null}
      </p>
      {deck.notes ? <p className="share-notes">{deck.notes}</p> : null}
      <p className="share-actions">
        <Link className="button button-compact" href={`/?deck=${encodeURIComponent(deck.share_token)}`}>
          Open in Deck Lab
        </Link>
      </p>
      <div className="share-layout">
        <div>
          <DeckSection title="Deck list" cards={deck.mainboard} deck={deck} notes={notes} />
          <DeckSection title="Sideboard" cards={deck.sideboard} deck={deck} notes={notes} />
        </div>
        <aside className="panel share-aside">
          <ManaCurveChart points={deck.mana_curve} />
          {deck.key_cards.length ? (
            <div className="share-key-cards">
              <h2 className="label">Key cards</h2>
              <ul className="card-list">
                {deck.key_cards.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </aside>
      </div>
    </main>
  );
}
