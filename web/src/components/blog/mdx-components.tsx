import Link from "next/link";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { AdSlot } from "@/components/ad-slot";
import { ADSENSE_IN_ARTICLE_SLOT } from "@/lib/ads";
import { AFFILIATE_DISCLOSURE, externalAnchorRel, isAffiliateUrl, tcgplayerMassEntryUrl } from "@/lib/affiliate";
import { getPost, isCategory, slugify } from "@/lib/blog";
import { catalogFetchedAt, getCatalogDeck } from "@/lib/example-catalog";
import { exampleBuilderHref } from "@/lib/example-decks";
import type { FormatName } from "@/lib/types";

const FORMATS: FormatName[] = ["standard", "modern", "pioneer", "legacy", "commander"];

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && typeof node === "object" && "props" in node) {
    return textOf((node as { props: { children?: ReactNode } }).props.children);
  }
  return "";
}

/** "Try this in Deck Lab": opens the builder with the format and brief filled in. */
export function DeckLabCTA({
  format,
  brief,
  title = "Try it in Deck Lab",
  children,
}: {
  format?: FormatName;
  brief?: string;
  title?: string;
  children?: ReactNode;
}) {
  const params = new URLSearchParams();
  if (format && FORMATS.includes(format)) params.set("format", format);
  if (brief) params.set("brief", brief);
  const query = params.toString();
  const href = `/${query ? `?${query}` : ""}#builder`;
  return (
    <aside className="blog-cta">
      <strong className="blog-cta-title">{title}</strong>
      <div className="blog-cta-body">
        {children ?? <p>Build a legal, playable deck around this idea and see why each card made the list.</p>}
      </div>
      <Link className="button blog-cta-button" href={href}>
        {brief ? `Build: “${brief}”` : "Open the deck builder"}
      </Link>
    </aside>
  );
}

/** In-article ad break. Renders nothing until AdSense and its slot are configured. */
export function InArticleAd() {
  return <AdSlot slot={ADSENSE_IN_ARTICLE_SLOT} className="blog-ad" />;
}

/** Official product list, with a button that opens the builder prefilled via ?example=. */
export function DeckBlock({ id }: { id: string }) {
  const deck = getCatalogDeck(id);
  if (!deck) {
    return <p>Example deck “{id}” is not in the priced catalog.</p>;
  }
  const fetchedAt = catalogFetchedAt();
  const buyUrl = tcgplayerMassEntryUrl([
    ...deck.mainboard,
    ...deck.sideboard,
    ...(deck.commander ? [{ name: deck.commander, quantity: 1 }] : []),
  ]);
  const showDisclosure = isAffiliateUrl(buyUrl);
  const kill = deck.analysis.goldfish.avg_kill_turn;
  return (
    <section className="deck-block" aria-label={deck.name}>
      <h3 className="deck-block-title">{deck.name}</h3>
      <p className="deck-block-meta">
        {deck.type}, released {deck.release_date}. Product-printing total ${deck.analysis.total_cost_usd.toFixed(2)}{" "}
        (MTGJSON AllPricesToday, {fetchedAt || "the catalog fetch"}).
        {deck.analysis.unpriced?.length
          ? ` Priced cards only, ${deck.analysis.unpriced.length} unpriced (${deck.analysis.unpriced.join(", ")}).`
          : ""}
        {kill != null
          ? ` Goldfish average winning turn ${kill} over ${deck.analysis.goldfish.games} games.`
          : ` Goldfish win rate ${(deck.analysis.goldfish.win_rate * 100).toFixed(0)}% over ${deck.analysis.goldfish.games} games.`}
      </p>
      {deck.commander ? (
        <p>
          <strong>Commander:</strong> {deck.commander}
        </p>
      ) : null}
      <div className="deck-block-list">
        <ul>
          {deck.mainboard.map((card) => (
            <li key={card.name}>
              {card.quantity} {card.name}
            </li>
          ))}
        </ul>
        {deck.sideboard.length ? (
          <>
            <p>
              <strong>Sideboard</strong>
            </p>
            <ul>
              {deck.sideboard.map((card) => (
                <li key={`side-${card.name}`}>
                  {card.quantity} {card.name}
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </div>
      <p className="deck-block-actions">
        <Link className="button blog-cta-button" href={exampleBuilderHref(deck.id)}>
          Open this list in the deck builder
        </Link>
      </p>
      <p className="deck-block-sources">
        <a href={buyUrl} target="_blank" rel="sponsored nofollow noopener noreferrer">
          Price this list on TCGplayer
        </a>
        {deck.source_url ? (
          <>
            {" · "}
            <a href={deck.source_url}>Wizards source</a>
          </>
        ) : null}
        {" · "}
        <a href={deck.mtgjson_deck_url}>MTGJSON deck file</a>
      </p>
      {showDisclosure ? <p className="affiliate-disclosure">{AFFILIATE_DISCLOSURE}</p> : null}
    </section>
  );
}

/** Wizards Fan Content Policy notice. Shown on every reviewed guide. */
export function FanContentNotice() {
  return (
    <aside className="blog-callout">
      <strong className="blog-callout-title">Fan Content</strong>
      <p>
        This is unofficial Fan Content permitted under the{" "}
        <a href="https://company.wizards.com/en/legal/fancontentpolicy">Fan Content Policy</a>. Not approved/endorsed
        by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.
      </p>
    </aside>
  );
}

export function Callout({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <aside className="blog-callout">
      {title ? <strong className="blog-callout-title">{title}</strong> : null}
      <div>{children}</div>
    </aside>
  );
}

function Heading2(props: ComponentPropsWithoutRef<"h2">) {
  const id = slugify(textOf(props.children));
  return (
    <h2 id={id} {...props}>
      <a href={`#${id}`} className="blog-heading-anchor">
        {props.children}
      </a>
    </h2>
  );
}

function Heading3(props: ComponentPropsWithoutRef<"h3">) {
  return <h3 id={slugify(textOf(props.children))} {...props} />;
}

function Anchor({ href = "", ...props }: ComponentPropsWithoutRef<"a">) {
  // A link to a guide that hasn't published yet (scheduled for a later day)
  // renders as plain text, and becomes a link once that guide is live.
  const guide = href.match(/^\/blog\/([a-z0-9-]+)/)?.[1];
  if (guide && !isCategory(guide) && !getPost(guide)) return <span>{props.children}</span>;
  if (href.startsWith("/")) return <Link href={href} {...props} />;
  return <a {...props} href={href} target="_blank" rel={externalAnchorRel(href)} />;
}

function Table(props: ComponentPropsWithoutRef<"table">) {
  return (
    <div className="blog-table-wrap">
      <table {...props} />
    </div>
  );
}

export const mdxComponents = {
  h2: Heading2,
  h3: Heading3,
  a: Anchor,
  table: Table,
  DeckLabCTA,
  DeckBlock,
  FanContentNotice,
  InArticleAd,
  Callout,
};
