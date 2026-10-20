import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { PostCard } from "@/components/blog/post-card";
import { DeckWorkshop } from "@/components/deck-workshop";
import { allPosts } from "@/lib/blog";

// Re-render hourly so scheduled guides appear on their date (BLOG_REVALIDATE_SECONDS).
export const revalidate = 3600;

export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

const FORMATS = [
  {
    name: "Standard",
    text: "The newest sets only. A rotating, budget-friendlier 60-card format.",
    guide: "/blog/mtg-formats-explained",
  },
  {
    name: "Pioneer",
    text: "Cards from Return to Ravnica forward. A large, non-rotating pool without Modern's oldest staples.",
    guide: "/blog/mtg-formats-explained",
  },
  {
    name: "Modern",
    text: "Cards from Eighth Edition forward. Fast, powerful and deep.",
    guide: "/blog/mtg-formats-explained",
  },
  {
    name: "Legacy",
    text: "Nearly every card ever printed, with a ban list. Brainstorm, Force of Will and decades of history.",
    guide: "/blog/mtg-formats-explained",
  },
  {
    name: "Commander",
    text: "100-card singleton decks led by a legendary commander. Multiplayer, social, and the most popular way to play.",
    guide: "/blog/what-is-commander-edh",
  },
];

const FAQ = [
  {
    q: "Is MTG Deck Lab free?",
    a: "Yes. Building, analyzing, saving and sharing decks is free, with no account required.",
  },
  {
    q: "Are the decks legal?",
    a: "Every deck is checked against the chosen format before it is shown: card legality, deck size, copy limits and, for Commander, color identity and singleton rules. Anything that fails the check is fixed or reported, never silently returned.",
  },
  {
    q: "How does it choose the cards?",
    a: "It starts from an archetype list for your format and strategy, then fills each role (threats, removal, card draw, ramp, lands) from a database of more than 30,000 cards, profiled from their rules text. Every card gets a short note explaining why it is in the deck.",
  },
  {
    q: "Can I build on a budget?",
    a: "Yes. Set a price limit and expensive cards are replaced with cheaper ones that do the same job. Each deck shows an estimated price and a one-click TCGplayer cart.",
  },
  {
    q: "Does it support Commander brackets?",
    a: "Yes. Deck Lab estimates a Commander deck's bracket under the official bracket system, and it can build toward the bracket your playgroup uses.",
  },
  {
    q: "Can it improve a deck I already have?",
    a: "Paste a decklist into the “Analyze my deck” tab to see its mana curve, roles and closest archetype, along with suggestions for what to change.",
  },
];

export default function HomePage() {
  const latest = allPosts().slice(0, 6);
  const faqJsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: FAQ.map((item) => ({
      "@type": "Question",
      name: item.q,
      acceptedAnswer: { "@type": "Answer", text: item.a },
    })),
  };
  return (
    <main className="shell">
      <header className="hero hero-compact">
        <div className="hero-copy">
          <div className="eyebrow">Meta-aware deckbuilding</div>
          <h1 className="headline">MTG Deck Lab</h1>
          <p className="subhead">Pick a format, colors, and strategy. Get a legal deck with transparent provenance.</p>
        </div>
        <ul className="hero-bullets" aria-label="What this builds">
          <li><strong>Honest provenance</strong><span>Every result says what it was built from.</span></li>
          <li><strong>Legality enforced</strong><span>Color identity gated end-to-end.</span></li>
          <li><strong>Build or analyze</strong><span>Generate, or import for coaching.</span></li>
        </ul>
      </header>
      {/* Suspense wrapper required by Next.js 14 when child components use
          useSearchParams (DeckWorkshop reads ?deck=<id> on mount for share
          links, and ?format= / ?brief= from guide links). */}
      <div id="builder">
        <Suspense fallback={null}>
          <DeckWorkshop />
        </Suspense>
      </div>

      {/* Server-rendered copy below the tool: the builder itself is client-side,
          so this is what crawlers and AdSense reviewers read. */}
      <section className="home-section" aria-labelledby="how-heading">
        <h2 id="how-heading">How MTG Deck Lab works</h2>
        <ol className="home-steps">
          <li>
            <strong>Describe the deck.</strong> Choose a format, colors and a strategy such as aggro, control, combo or
            tokens, or just write a sentence like &ldquo;mono-red burn under $50&rdquo;. For Commander, pick a commander
            or let Deck Lab recommend one.
          </li>
          <li>
            <strong>Get a complete, legal list.</strong> Deck Lab assembles the deck from an archetype shell and fills
            every role, then checks it against the format&apos;s rules before showing it to you.
          </li>
          <li>
            <strong>Read the reasoning.</strong> Tap &ldquo;Why?&rdquo; next to any card, review the mana curve and role
            breakdown, read the game plan, and refine the deck in plain language (&ldquo;make it cheaper&rdquo;,
            &ldquo;add more removal&rdquo;).
          </li>
          <li>
            <strong>Save, share or buy it.</strong> Save the deck to get a share link, export it for MTG Arena, Moxfield or Archidekt, or
            open the whole list as a TCGplayer cart.
          </li>
        </ol>
      </section>

      <section className="home-section" aria-labelledby="formats-heading">
        <h2 id="formats-heading">Supported formats</h2>
        <div className="home-formats">
          {FORMATS.map((format) => (
            <article key={format.name} className="panel home-format">
              <h3>{format.name}</h3>
              <p className="muted">{format.text}</p>
              <Link href={format.guide}>Learn the format →</Link>
            </article>
          ))}
        </div>
      </section>

      <section className="home-section" aria-labelledby="faq-heading">
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd) }} />
        <h2 id="faq-heading">Frequently asked questions</h2>
        <dl className="home-faq">
          {FAQ.map((item) => (
            <div key={item.q}>
              <dt>{item.q}</dt>
              <dd>{item.a}</dd>
            </div>
          ))}
        </dl>
      </section>

      {latest.length ? (
        <section className="home-section" aria-labelledby="guides-heading">
          <div className="blog-section-head">
            <h2 id="guides-heading">Guides for every level</h2>
            <Link href="/blog" className="muted">All guides →</Link>
          </div>
          <div className="blog-grid">
            {latest.map((post) => (
              <PostCard key={post.slug} post={post} />
            ))}
          </div>
        </section>
      ) : null}
    </main>
  );
}
