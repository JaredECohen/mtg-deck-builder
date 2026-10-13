"use client";

import { SOURCE_LABEL } from "./provenance-banner";
import type { DeckAlternative } from "@/lib/types";

type Props = {
  alternatives: DeckAlternative[];
  loading: boolean;
  onBuild: (alternative: DeckAlternative) => void;
  onOpenCard: (name: string) => void;
};

/** "Also consider": runner-up shells, each buildable with the same constraints. */
export function AlternativesPanel({ alternatives, loading, onBuild, onOpenCard }: Props) {
  if (!alternatives.length) return null;
  return (
    <section className="panel results-card" aria-labelledby="alternatives-heading">
      <h3 id="alternatives-heading" className="label">Also consider</h3>
      <p className="muted field-help">Other shells that fit your request. Building one keeps your format, colors and expert settings.</p>
      <ul className="alternatives-list">
        {alternatives.map((alternative) => (
          <li key={`${alternative.name}-${alternative.commander ?? ""}`} className="alternative-card">
            <div className="alternative-head">
              <strong>{alternative.commander ? `${alternative.commander}: ${alternative.name}` : alternative.name}</strong>
              <span className="status-pill">{SOURCE_LABEL[alternative.source_type]?.label ?? alternative.source_type}</span>
              {alternative.colors.length ? <span className="muted">{alternative.colors.join("")}</span> : null}
            </div>
            {alternative.summary ? <p className="muted">{alternative.summary}</p> : null}
            {alternative.tags.length ? (
              <ul className="chips tag-chips" aria-label="Tags">
                {alternative.tags.slice(0, 5).map((tag) => (
                  <li key={tag} className="tag-chip">{tag}</li>
                ))}
              </ul>
            ) : null}
            {alternative.key_cards.length ? (
              <p className="alternative-cards">
                <span className="muted">Key cards: </span>
                {alternative.key_cards.slice(0, 6).map((name, index, list) => (
                  <span key={name}>
                    <button type="button" className="inline-card" onClick={() => onOpenCard(name)}>{name}</button>
                    {index < list.length - 1 ? ", " : ""}
                  </span>
                ))}
              </p>
            ) : null}
            <button
              type="button"
              className="button secondary button-compact"
              disabled={loading}
              onClick={() => onBuild(alternative)}
              aria-label={`Build ${alternative.name} instead`}
            >
              Build this
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
