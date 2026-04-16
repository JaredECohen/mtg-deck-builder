import { DeckWorkshop } from "@/components/deck-workshop";

export default function HomePage() {
  return (
    <main className="shell">
      <section className="hero">
        <div>
          <div className="eyebrow">Meta-aware deckbuilding</div>
          <h1 className="headline">Build legal, sharp MTG decks from a few constraints.</h1>
          <p className="subhead">
            Choose a format, define your colors or playstyle, and generate a tuned deck with transparent reasoning, validation, and easy refinements.
          </p>
        </div>
        <div className="panel results-card panel-strong">
          <div className="label">Core Product Promise</div>
          <div className="stats">
            <div className="stat">
              <span className="muted">Formats</span>
              <strong>4</strong>
            </div>
            <div className="stat">
              <span className="muted">Modes</span>
              <strong>3</strong>
            </div>
            <div className="stat">
              <span className="muted">Focus</span>
              <strong>Hybrid</strong>
            </div>
          </div>
          <p className="muted" style={{ marginTop: 16 }}>
            Retrieval-backed shells, first-principles adaptation, and deterministic legality checks.
          </p>
        </div>
      </section>
      <DeckWorkshop />
    </main>
  );
}

