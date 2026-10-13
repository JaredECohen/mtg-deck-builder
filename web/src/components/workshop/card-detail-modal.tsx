"use client";

import { useEffect, useRef, useState } from "react";

import type { CardDetailState } from "@/hooks/use-card-detail";
import { AFFILIATE_DISCLOSURE, tcgplayerSearchUrl } from "@/lib/affiliate";

type Props = {
  detail: CardDetailState;
};

const FOCUSABLE_SELECTOR = 'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** Card image with a skeleton until the bytes arrive. Keyed by src by the caller. */
function CardImage({ src, alt }: { src: string; alt: string }) {
  const [state, setState] = useState<"loading" | "loaded" | "failed">("loading");
  return (
    <>
      {state === "loading" ? <div className="card-image-skeleton" aria-hidden="true" /> : null}
      {state === "failed" ? <p className="muted">The card image could not be loaded.</p> : null}
      {/* Scryfall images are already sized and cached; next/image would need a remote loader config. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt}
        className={`card-image ${state === "loaded" ? "" : "card-image-pending"}`}
        onLoad={() => setState("loaded")}
        onError={() => setState("failed")}
      />
    </>
  );
}

export function CardDetailModal({ detail }: Props) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const { name, card, loading, error, context, similar, similarLoading, similarError, open, close } = detail;

  // Move focus into the dialog on open, and again when a similar card replaces
  // the one on screen (the clicked chip disappears with the old list).
  useEffect(() => {
    if (name) closeRef.current?.focus();
  }, [name]);

  if (!name) return null;

  // Dependency-free Tab focus trap: keep keyboard focus cycling inside the
  // dialog while it is open.
  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab") return;
    const root = dialogRef.current;
    if (!root) return;
    const focusable = root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  const imageSrc = card?.image_uri || card?.faces.find((face) => face.image_uri)?.image_uri || null;
  const filterNote = [
    context.format ? `legal in ${context.format[0].toUpperCase()}${context.format.slice(1)}` : null,
    context.colors ? `within ${context.colors.length ? context.colors.join("") : "colorless"}` : null
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <div className="card-modal-backdrop" role="presentation" onClick={close}>
      <div
        ref={dialogRef}
        className="card-modal panel panel-strong"
        role="dialog"
        aria-modal="true"
        aria-labelledby="card-detail-name"
        aria-describedby={card ? "card-detail-oracle" : undefined}
        aria-busy={loading}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="card-modal-header">
          <div>
            <div className="label">Card Detail</div>
            <h3 id="card-detail-name" style={{ marginTop: 0, marginBottom: 6 }}>{name}</h3>
            <p className="muted" style={{ margin: 0 }}>{card?.type_line || (loading ? "Loading card details…" : "Card details")}</p>
          </div>
          <button type="button" className="chip" onClick={close} ref={closeRef}>Close</button>
        </div>
        <div className="card-modal-grid">
          <div className="card-image-shell">
            {loading ? <div className="card-image-skeleton" role="img" aria-label="Loading card image" /> : null}
            {!loading && imageSrc ? <CardImage key={imageSrc} src={imageSrc} alt={name} /> : null}
            {!loading && !imageSrc ? <p className="muted">No image available for this card.</p> : null}
          </div>
          <div className="card-copy">
            {loading ? (
              <div className="card-copy-skeleton" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
            ) : card ? (
              <>
                <p><strong>Mana Cost:</strong> {card.mana_cost || "-"}</p>
                {card.rarity ? <p><strong>Rarity:</strong> {card.rarity}</p> : null}
                <p><strong>Oracle Text:</strong></p>
                <pre id="card-detail-oracle" className="oracle-text">{card.oracle_text || "No rules text available."}</pre>
                {card.faces.length ? (
                  <div>
                    <p><strong>Faces:</strong></p>
                    <ul className="card-list">
                      {card.faces.map((face, index) => (
                        <li key={`${face.name ?? "face"}-${index}`} className="card-row" style={{ display: "block" }}>
                          <strong>{face.name ?? `Face ${index + 1}`}</strong>
                          <div className="muted">{face.type_line}</div>
                          <pre className="oracle-text">{face.oracle_text || "No face text available."}</pre>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {card.price_usd && Number.isFinite(card.price_usd) ? <p><strong>Cached Price:</strong> ${card.price_usd.toFixed(2)}</p> : null}
                {card.tags.length ? <p><strong>Tags:</strong> {card.tags.join(", ")}</p> : null}
              </>
            ) : null}
            <div className="export-row" style={{ marginTop: 12 }}>
              <a
                className="button"
                href={card?.purchase_links?.tcgplayer || tcgplayerSearchUrl(name)}
                target="_blank"
                rel="noreferrer sponsored"
              >
                Buy on TCGplayer
              </a>
              {card?.purchase_links?.scryfall ? (
                <a className="button secondary" href={card.purchase_links.scryfall} target="_blank" rel="noreferrer">Open Scryfall</a>
              ) : null}
              {card?.purchase_links?.cardmarket ? (
                <a className="button secondary" href={card.purchase_links.cardmarket} target="_blank" rel="noreferrer">Buy on Cardmarket</a>
              ) : null}
            </div>
            <p className="muted" style={{ marginTop: 8, fontSize: "0.75rem" }}>{AFFILIATE_DISCLOSURE}</p>
            {error ? <p className="workflow-error" role="alert">{error}</p> : null}

            <section className="similar-cards" aria-labelledby="similar-cards-heading">
              <div className="label" id="similar-cards-heading">Similar cards you could play</div>
              {filterNote ? <p className="muted similar-cards-note">Filtered to cards {filterNote}.</p> : null}
              {similarLoading ? <p className="muted">Finding similar cards…</p> : null}
              {!similarLoading && similarError ? <p className="muted">{similarError}</p> : null}
              {!similarLoading && !similarError && similar && !similar.length ? (
                <p className="muted">No close matches in this format and color identity.</p>
              ) : null}
              {similar?.length ? (
                <ul className="chips similar-card-list">
                  {similar.map((entry) => (
                    <li key={entry.name}>
                      <button type="button" className="chip" onClick={() => void open(entry.name, context)}>
                        {entry.name}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
