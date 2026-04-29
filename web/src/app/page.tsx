import { DeckWorkshop } from "@/components/deck-workshop";

export default function HomePage() {
  return (
    <main className="shell">
      <header className="hero hero-compact">
        <div className="hero-copy">
          <div className="eyebrow">Meta-aware deckbuilding</div>
          <h1 className="headline">Build legal MTG decks from a few constraints.</h1>
          <p className="subhead">
            Pick a format, set colors and a strategy, and get a tuned deck with transparent provenance — corpus-backed shells, deterministic legality, and honest confidence scoring.
          </p>
        </div>
        <ul className="hero-bullets" aria-label="What this builds">
          <li><strong>Corpus + fallback retrieval</strong><span>Every deck is labeled with where it came from.</span></li>
          <li><strong>Hard legality gate</strong><span>Commander color identity is enforced end-to-end.</span></li>
          <li><strong>Generate or analyze</strong><span>Build from constraints, or import a list and get coaching.</span></li>
        </ul>
      </header>
      <DeckWorkshop />
    </main>
  );
}
