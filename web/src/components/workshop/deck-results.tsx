"use client";

import { useState, type ReactNode } from "react";

import { ProvenanceBanner } from "./provenance-banner";
import { AFFILIATE_DISCLOSURE, amazonSearchUrl } from "@/lib/affiliate";
import type { ExportTarget } from "@/lib/api";
import { groupByType } from "@/lib/group-by-type";
import type { ArchetypePackage, CardRef, CardTypeMap, CommanderProfile, DeckResponse, MetaSummaryResponse } from "@/lib/types";

type Props = {
  deck: DeckResponse;
  meta: MetaSummaryResponse | null;
  selectedCommanderName: string;
  selectedCommanderProfile: CommanderProfile | null;
  chatPanel: ReactNode;
  onExport: (target: ExportTarget) => void;
  exportContent: string;
  onOpenCard: (name: string) => void;
  onApplyOptimized?: (next: DeckResponse) => void;
};

function PackageList({ title, packages }: { title: string; packages: ArchetypePackage[] }) {
  if (!packages.length) return null;
  return (
    <div className="panel results-card">
      <div className="label">{title}</div>
      <ul className="card-list">
        {packages.map((item) => (
          <li key={`${title}-${item.name}`} className="card-row">
            <span>{item.name}</span>
            <span className="muted">
              {item.inclusion_rate ? `${Math.round(item.inclusion_rate * 100)}%` : ""}
              {item.average_quantity ? ` • ${item.average_quantity} avg` : ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DeckCardRow({ card, suffix, quantityLabel, onOpen }: { card: CardRef; suffix: string; quantityLabel: string; onOpen: (name: string) => void }) {
  return (
    <li key={`${card.name}-${card.quantity}-${suffix}`} className="card-row card-row-action">
      <button type="button" className="card-button" onClick={() => onOpen(card.name)}>
        <span>{card.name}</span>
        <span className="muted">{quantityLabel}</span>
      </button>
    </li>
  );
}

export function GroupedDeckList({
  cards,
  typeMap,
  emptyLabel,
  suffix,
  onOpenCard
}: {
  cards: CardRef[];
  typeMap: CardTypeMap | undefined;
  emptyLabel?: string;
  suffix: string;
  onOpenCard: (name: string) => void;
}) {
  const sections = groupByType(cards, typeMap);
  if (!sections.length) {
    return emptyLabel ? <p className="muted" style={{ marginTop: 4 }}>{emptyLabel}</p> : null;
  }
  return (
    <div className="deck-type-sections">
      {sections.map((section) => (
        <div key={`${suffix}-${section.type}`} className="deck-type-section">
          <div className="deck-type-heading">
            <span>{section.label}</span>
            <span className="muted">{section.count}</span>
          </div>
          <ul className="card-list">
            {section.cards.map((card) => (
              <DeckCardRow
                key={`${suffix}-${section.type}-${card.name}`}
                card={card}
                suffix={`${suffix}-${section.type}`}
                quantityLabel={`${card.quantity}x`}
                onOpen={onOpenCard}
              />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

const BASIC_LAND_NAMES = new Set(["Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"]);

function ShopDeckPanel({ deck }: { deck: DeckResponse }) {
  // Unique non-basic cards across mainboard, sideboard, and commander —
  // basics aren't worth a marketplace click.
  const seen = new Set<string>();
  const shoppable: CardRef[] = [];
  const commanderRefs: CardRef[] = deck.commander ? [{ name: deck.commander, quantity: 1 }] : [];
  for (const ref of [...commanderRefs, ...deck.mainboard, ...deck.sideboard]) {
    if (BASIC_LAND_NAMES.has(ref.name) || seen.has(ref.name)) continue;
    seen.add(ref.name);
    shoppable.push(ref);
  }
  if (!shoppable.length) return null;
  return (
    <div className="panel results-card">
      <div className="label">Shop This Deck</div>
      <p className="muted" style={{ marginTop: 0 }}>
        Find singles on Amazon — each link searches for that card.
      </p>
      <details>
        <summary style={{ cursor: "pointer" }}>
          {shoppable.length} cards to shop
        </summary>
        <ul className="card-list" style={{ marginTop: 8 }}>
          {shoppable.map((card) => (
            <li key={`shop-${card.name}`} className="card-row">
              <span>{card.quantity}x {card.name}</span>
              <a
                href={amazonSearchUrl(card.name)}
                target="_blank"
                rel="noreferrer sponsored"
                className="chip"
              >
                Amazon
              </a>
            </li>
          ))}
        </ul>
      </details>
      <p className="muted" style={{ marginTop: 8, fontSize: "0.75rem" }}>{AFFILIATE_DISCLOSURE}</p>
    </div>
  );
}

export function DeckResults({
  deck,
  meta,
  selectedCommanderName,
  selectedCommanderProfile,
  chatPanel,
  onExport,
  exportContent,
  onOpenCard,
  onApplyOptimized
}: Props) {
  const [exportTarget, setExportTarget] = useState<ExportTarget>("plain");

  return (
    <>
      <ProvenanceBanner
        provenance={deck.provenance}
        commanderRequested={Boolean(deck.commander)}
        currentDeck={deck}
        onApplyOptimized={onApplyOptimized}
      />

      <div className="panel results-card">
        <div className="deck-columns">
          <div>
            <div className="label">
              Mainboard
              <span className="muted" style={{ marginLeft: 8, fontWeight: "normal" }}>
                {deck.mainboard.reduce((sum, ref) => sum + ref.quantity, 0)} cards
              </span>
            </div>
            <GroupedDeckList cards={deck.mainboard} typeMap={deck.card_types} suffix="main" onOpenCard={onOpenCard} />
          </div>
          <div>
            <div className="label">
              {deck.commander ? "Commander / Sideboard" : "Sideboard"}
              {deck.commander ? (
                <span className="chip" style={{ marginLeft: 8, fontSize: "0.72rem", opacity: 0.85 }}>
                  {selectedCommanderName && selectedCommanderName === deck.commander ? "Your pick" : "Recommended"}
                </span>
              ) : null}
            </div>
            {deck.commander ? (
              <ul className="card-list" style={{ marginBottom: 12 }}>
                <DeckCardRow card={{ name: deck.commander, quantity: 1 }} suffix="commander" quantityLabel="Commander" onOpen={onOpenCard} />
              </ul>
            ) : null}
            {deck.sideboard.length ? (
              <GroupedDeckList cards={deck.sideboard} typeMap={deck.card_types} suffix="sideboard" onOpenCard={onOpenCard} />
            ) : (
              <ul className="card-list">
                {deck.card_notes.slice(0, 6).map((note) => (
                  <DeckCardRow
                    key={`note-${note.name}`}
                    card={{ name: note.name, quantity: 1 }}
                    suffix="note"
                    quantityLabel="note"
                    onOpen={onOpenCard}
                  />
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      <div className="panel results-card">
        <div className="label">Why This Deck</div>
        <ul className="card-list">
          {deck.explanation.map((item, index) => (
            <li key={`why-${index}`} className="card-row"><span>{item}</span></li>
          ))}
        </ul>
      </div>

      {deck.sections.length ? (
        <div className="panel results-card">
          <div className="label">Deck Breakdown</div>
          <div className="card-list">
            {deck.sections.map((section) => (
              <div key={section.title} className="card-row" style={{ display: "block" }}>
                <strong>{section.title}</strong>
                <p className="muted" style={{ marginTop: 6 }}>{section.summary}</p>
                {section.bullets.length ? (
                  <ul style={{ margin: "8px 0 0 18px" }}>
                    {section.bullets.map((bullet) => (
                      <li key={`${section.title}-${bullet}`}>{bullet}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {selectedCommanderProfile && deck.commander === selectedCommanderProfile.card.name ? (
        <div className="panel results-card panel-strong">
          <div className="label">Selected Commander</div>
          <h3 style={{ marginTop: 0, marginBottom: 8 }}>{selectedCommanderProfile.card.name}</h3>
          <p className="muted" style={{ marginTop: 0 }}>{selectedCommanderProfile.strategy_summary}</p>
          <div className="stats stats-four" style={{ marginTop: 16 }}>
            <div className="stat">
              <span className="muted">Colors</span>
              <strong>{selectedCommanderProfile.colors.join("") || "-"}</strong>
            </div>
            <div className="stat">
              <span className="muted">Support</span>
              <strong>{selectedCommanderProfile.support_depth}</strong>
            </div>
            <div className="stat">
              <span className="muted">Ramp Avg</span>
              <strong>{selectedCommanderProfile.average_ramp?.toFixed(0) ?? "-"}</strong>
            </div>
            <div className="stat">
              <span className="muted">Draw Avg</span>
              <strong>{selectedCommanderProfile.average_draw?.toFixed(0) ?? "-"}</strong>
            </div>
          </div>
          {selectedCommanderProfile.tags.length ? (
            <p className="muted" style={{ marginTop: 12 }}>Tags: {selectedCommanderProfile.tags.join(", ")}</p>
          ) : null}
        </div>
      ) : null}

      {deck.mechanics.length ? (
        <div className="panel results-card">
          <div className="label">Key Mechanics</div>
          <ul className="card-list">
            {deck.mechanics.map((mechanic) => (
              <li key={mechanic.label} className="card-row" style={{ display: "block" }}>
                <strong>{mechanic.label}</strong>
                <p className="muted" style={{ marginTop: 6 }}>{mechanic.summary}</p>
                <span>{mechanic.cards.join(", ")}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {(deck.role_summary.length || deck.mana_curve.length) ? (
        <div className="panel results-card">
          <div className="label">Structure</div>
          <div className="deck-columns">
            <div>
              <div className="label">Roles</div>
              <ul className="card-list">
                {deck.role_summary.map((item) => (
                  <li key={item.role} className="card-row">
                    <span>{item.role}</span>
                    <span className="muted">{item.total_cards}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="label">Mana Curve</div>
              <ul className="card-list">
                {deck.mana_curve.map((point) => (
                  <li key={point.mana_value} className="card-row">
                    <span>{point.mana_value === 6 ? "6+" : point.mana_value}</span>
                    <span className="muted">{point.card_count}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      ) : null}

      {deck.warnings.length ? (
        <div className="panel results-card">
          <div className="label">Quality Warnings</div>
          <p className="muted" style={{ marginTop: 0 }}>These do not block legality but are worth tightening.</p>
          <ul className="card-list">
            {deck.warnings.map((item, index) => (
              <li key={`warning-${index}`} className="card-row"><span>{item}</span></li>
            ))}
          </ul>
        </div>
      ) : null}

      {deck.validation_errors.length ? (
        <div className="panel results-card panel-error">
          <div className="label">Blocking Legality Errors</div>
          <p className="muted" style={{ marginTop: 0 }}>The deck cannot be played until these are resolved.</p>
          <ul className="card-list">
            {deck.validation_errors.map((item, index) => (
              <li key={`error-${index}`} className="card-row"><span>{item}</span></li>
            ))}
          </ul>
        </div>
      ) : null}

      {deck.selected_archetype ? (
        <>
          <div className="panel results-card panel-strong">
            <div className="label">Selected Archetype</div>
            <h3 style={{ marginTop: 0, marginBottom: 8 }}>{deck.selected_archetype.name}</h3>
            <p className="muted" style={{ marginTop: 0 }}>{deck.selected_archetype.strategy}</p>
            <div className="stats stats-three" style={{ marginTop: 18 }}>
              <div className="stat">
                <span className="muted">Sources</span>
                <strong>{deck.selected_archetype.source_count}</strong>
              </div>
              <div className="stat">
                <span className="muted">Avg Place</span>
                <strong>{deck.selected_archetype.avg_placement ? deck.selected_archetype.avg_placement.toFixed(1) : "-"}</strong>
              </div>
              <div className="stat">
                <span className="muted">Tags</span>
                <strong style={{ fontSize: 16 }}>{deck.selected_archetype.tags.slice(0, 3).join(" / ") || "-"}</strong>
              </div>
            </div>
          </div>

          <PackageList title="Core Cards" packages={deck.selected_archetype.metadata.core_cards} />
          <PackageList title="Flex Slots" packages={deck.selected_archetype.metadata.flex_cards} />
          <PackageList title="Land Packages" packages={deck.selected_archetype.metadata.land_packages} />
          <PackageList title="Common Sideboard Packages" packages={deck.selected_archetype.metadata.sideboard_packages} />
          {deck.selected_archetype.metadata.commander_package ? (
            <>
              <PackageList title="Commander Signature Cards" packages={deck.selected_archetype.metadata.commander_package.signature_cards} />
              <PackageList title="Commander Support Packages" packages={deck.selected_archetype.metadata.commander_package.synergy_packages} />
            </>
          ) : null}
        </>
      ) : null}

      {meta?.archetypes?.length ? (
        <div className="panel results-card">
          <div className="label">Format Meta Snapshot</div>
          <ul className="card-list">
            {meta.archetypes.slice(0, 5).map((archetype) => (
              <li key={archetype.id} className="card-row">
                <span>
                  {archetype.name}
                  {archetype.tags?.slice(0, 2).map((tag) => (
                    <span key={tag} className="chip" style={{ marginLeft: 6, fontSize: "0.72rem" }}>{tag}</span>
                  ))}
                </span>
                <span className="muted">
                  {archetype.source_count} decks
                  {archetype.avg_placement ? ` • avg ${archetype.avg_placement.toFixed(1)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <ShopDeckPanel deck={deck} />

      {chatPanel}

      <div className="panel results-card">
        <div className="label">Export Deck</div>
        <div className="export-row">
          <select className="select" value={exportTarget} onChange={(event) => setExportTarget(event.target.value as ExportTarget)}>
            <option value="plain">Plain Text</option>
            <option value="arena">MTG Arena</option>
            <option value="csv">CSV</option>
            <option value="moxfield">Moxfield</option>
          </select>
          <button type="button" className="button secondary" onClick={() => onExport(exportTarget)}>Build Export</button>
        </div>
        {exportContent ? (
          <pre className="export-output">{exportContent}</pre>
        ) : (
          <p className="muted" style={{ marginTop: 12 }}>
            Render this list as plain text, Arena import text, CSV, or Moxfield formatting.
          </p>
        )}
      </div>
    </>
  );
}
