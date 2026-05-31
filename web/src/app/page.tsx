import { Suspense } from "react";

import { DeckWorkshop } from "@/components/deck-workshop";

export default function HomePage() {
  return (
    <main className="shell">
      <header className="hero hero-compact">
        <div className="hero-copy">
          <div className="eyebrow">Meta-aware deckbuilding</div>
          <h1 className="headline">MTG Deck Lab</h1>
          <p className="subhead">Pick a format, colors, and strategy. Get a legal deck with transparent provenance.</p>
        </div>
        <ul className="hero-bullets" aria-label="What this builds">
          <li><strong>Corpus-backed</strong><span>Sources labeled per card.</span></li>
          <li><strong>Legality enforced</strong><span>Color identity gated end-to-end.</span></li>
          <li><strong>Build or analyze</strong><span>Generate, or import for coaching.</span></li>
        </ul>
      </header>
      {/* Suspense wrapper required by Next.js 14 when child components use
          useSearchParams (DeckWorkshop reads ?deck=<id> on mount for share
          links). */}
      <Suspense fallback={null}>
        <DeckWorkshop />
      </Suspense>
    </main>
  );
}
