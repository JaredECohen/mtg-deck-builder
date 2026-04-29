"use client";

import type { CardRecord } from "@/lib/types";

type Props = {
  card: CardRecord;
  loading: boolean;
  error: string | null;
  onClose: () => void;
};

export function CardDetailModal({ card, loading, error, onClose }: Props) {
  return (
    <div className="card-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="card-modal panel panel-strong"
        role="dialog"
        aria-modal="true"
        aria-labelledby="card-detail-name"
        aria-describedby="card-detail-oracle"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="card-modal-header">
          <div>
            <div className="label">Card Detail</div>
            <h3 id="card-detail-name" style={{ marginTop: 0, marginBottom: 6 }}>{card.name}</h3>
            <p className="muted" style={{ margin: 0 }}>{card.type_line || "Card details"}</p>
          </div>
          <button type="button" className="chip" onClick={onClose}>Close</button>
        </div>
        <div className="card-modal-grid">
          <div className="card-image-shell">
            {loading ? <div style={{ width: 265, height: 370, background: "#e5e7eb", borderRadius: 8 }} aria-label="Loading card image" /> : null}
            {!loading && card.image_uri ? <img src={card.image_uri} alt={card.name} className="card-image" /> : null}
            {!loading && !card.image_uri && card.faces[0]?.image_uri ? <img src={card.faces[0].image_uri ?? ""} alt={card.name} className="card-image" /> : null}
            {!loading && !card.image_uri && !card.faces[0]?.image_uri ? <p className="muted">No image available for this card.</p> : null}
          </div>
          <div className="card-copy">
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
            {card.price_usd ? <p><strong>Cached Price:</strong> ${card.price_usd.toFixed(2)}</p> : null}
            {card.tags.length ? <p><strong>Tags:</strong> {card.tags.join(", ")}</p> : null}
            <div className="export-row" style={{ marginTop: 12 }}>
              {card.purchase_links?.scryfall ? (
                <a className="button secondary" href={card.purchase_links.scryfall} target="_blank" rel="noreferrer">Open Scryfall</a>
              ) : null}
              {card.purchase_links?.amazon_search ? (
                <a className="button secondary" href={card.purchase_links.amazon_search} target="_blank" rel="noreferrer">Search Amazon</a>
              ) : null}
            </div>
            {error ? <p style={{ color: "#fca5a5" }}>{error}</p> : null}
          </div>
        </div>
      </div>
    </div>
  );
}
