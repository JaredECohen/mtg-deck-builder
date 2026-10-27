"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AlternativesPanel } from "./alternatives-panel";
import { ColorSourceChart } from "./color-source-chart";
import { DeckChat } from "./deck-chat";
import { DeckDiffView } from "./deck-diff-view";
import { DeckExplanationTabs, HowToPlay } from "./deck-explanation";
import { DeckCardRow, GroupedDeckList, notesByCard } from "./deck-list";
import { ExportPanel } from "./export-panel";
import { ManaCurveChart } from "./mana-curve-chart";
import { ProvenanceBanner } from "./provenance-banner";
import { RevisionHistory } from "./revision-history";
import { useDeckChat } from "@/hooks/use-deck-chat";
import type { DeckRevision } from "@/hooks/use-deck-generator";
import { trackTcgplayerCartClicked } from "@/lib/analytics";
import { AFFILIATE_DISCLOSURE, tcgplayerMassEntryUrl, tcgplayerSearchUrl } from "@/lib/affiliate";
import { MAX_PROMPT_CHARS } from "@/lib/api";
import { cardCount } from "@/lib/deck-diff";
import type {
  ArchetypePackage,
  CardRef,
  CommanderProfile,
  DeckAlternative,
  DeckChanges,
  DeckDiffResult,
  DeckResponse,
  MetaSummaryResponse
} from "@/lib/types";

// Re-exported for the Analyze workflow, which renders the same grouped list.
export { GroupedDeckList } from "./deck-list";

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
  // The whole deck — including basics — goes into the one-click cart.
  const massEntryUrl = tcgplayerMassEntryUrl([...commanderRefs, ...deck.mainboard, ...deck.sideboard]);
  return (
    <section className="panel results-card" aria-labelledby="shop-heading">
      <h3 id="shop-heading" className="label">Shop This Deck</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        Buy the whole list in one TCGplayer cart at the cheapest available prices, or grab individual singles below.
      </p>
      <a
        href={massEntryUrl}
        target="_blank"
        rel="noreferrer sponsored"
        className="button"
        style={{ marginBottom: 12 }}
        onClick={() => trackTcgplayerCartClicked(deck.format)}
      >
        Buy entire deck on TCGplayer
      </a>
      <details>
        <summary style={{ cursor: "pointer" }}>{shoppable.length} cards to shop individually</summary>
        <ul className="card-list" style={{ marginTop: 8 }}>
          {shoppable.map((card) => (
            <li key={`shop-${card.name}`} className="card-row">
              <span>
                {card.quantity}x {card.name}
              </span>
              <a
                href={tcgplayerSearchUrl(card.name)}
                target="_blank"
                rel="noreferrer sponsored"
                className="chip"
                aria-label={`Buy ${card.name} on TCGplayer`}
              >
                TCGplayer
              </a>
            </li>
          ))}
        </ul>
      </details>
      <p className="muted" style={{ marginTop: 8, fontSize: "0.75rem" }}>{AFFILIATE_DISCLOSURE}</p>
    </section>
  );
}

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

type Props = {
  deck: DeckResponse;
  meta: MetaSummaryResponse | null;
  metaError: string | null;
  selectedCommanderName: string;
  selectedCommanderProfile: CommanderProfile | null;
  refinePrompt: string;
  onRefinePromptChange: (value: string) => void;
  onRefine: () => void;
  onOpenCard: (name: string) => void;
  /** Any request in flight (generate or refine). */
  loading: boolean;
  expertMode: boolean;
  /** What the latest refine changed, if the deck on screen came from one. */
  changes: DeckChanges | DeckDiffResult | null;
  revisions: DeckRevision[];
  onUndo: () => void;
  onRestore: (id: number) => void;
  onApplyOptimized: (next: DeckResponse) => void;
  onBuildAlternative: (alternative: DeckAlternative) => void;
};

export function DeckResults({
  deck,
  meta,
  metaError,
  selectedCommanderName,
  selectedCommanderProfile,
  refinePrompt,
  onRefinePromptChange,
  onRefine,
  onOpenCard,
  loading,
  expertMode,
  changes,
  revisions,
  onUndo,
  onRestore,
  onApplyOptimized,
  onBuildAlternative
}: Props) {
  // "Ask About This Deck". The chat API is stateless — the server gets the
  // current deck plus the transcript on every turn — so the conversation should
  // survive a refinement of the same deck (the refiner even renames it) and
  // start over when a different deck arrives (new generation, undo, a loaded
  // deck). This component sees both ways a refinement starts — its Refine button
  // and a chat proposal — so a deck change while one is in flight is "same deck";
  // any other deck change is a new one.
  const chat = useDeckChat();
  const { reset: resetChat, markApplied } = chat;
  const [pendingApply, setPendingApply] = useState<{ bubbleId: string; refinement: string } | null>(null);
  const refineInFlight = useRef(false);
  // The chat bubble whose proposal is being applied. It is marked "Applied"
  // only when the refined deck arrives, so a failed refine stays retryable.
  const applyingBubble = useRef<string | null>(null);
  const startRefine = useCallback(() => {
    refineInFlight.current = true;
    onRefine();
  }, [onRefine]);
  useEffect(() => {
    if (refineInFlight.current) {
      refineInFlight.current = false;
      if (applyingBubble.current) markApplied(applyingBubble.current);
      applyingBubble.current = null;
      return;
    }
    resetChat();
    setPendingApply(null);
  }, [deck, resetChat, markApplied]);
  useEffect(() => {
    // A refinement that failed leaves the deck unchanged; don't let its marker
    // swallow the reset for the next generation.
    if (!loading) {
      refineInFlight.current = false;
      applyingBubble.current = null;
    }
  }, [loading]);
  // A proposed change goes through the existing Refine flow: it lands in the
  // Refine box (visible, editable, undoable like any refinement) and the refine
  // fires once the parent's state carries it — the callback reads that state.
  useEffect(() => {
    if (!pendingApply || loading || refinePrompt !== pendingApply.refinement) return;
    applyingBubble.current = pendingApply.bubbleId;
    startRefine();
    setPendingApply(null);
  }, [pendingApply, refinePrompt, loading, startRefine]);

  const notes = useMemo(() => notesByCard(deck.card_notes), [deck.card_notes]);
  const isBo1 = deck.constraints?.match_type === "bo1";

  return (
    <>
      <ProvenanceBanner
        provenance={deck.provenance}
        commanderRequested={Boolean(deck.commander)}
        currentDeck={deck}
        onApplyOptimized={onApplyOptimized}
      />

      <section className="panel results-card" aria-label="Decklist">
        <div className="deck-columns">
          <div>
            <h3 className="label">
              Mainboard
              <span className="muted label-count">{cardCount(deck.mainboard)} cards</span>
            </h3>
            <GroupedDeckList cards={deck.mainboard} typeMap={deck.card_types} suffix="main" notes={notes} onOpenCard={onOpenCard} />
          </div>
          <div>
            {deck.commander ? (
              <>
                <h3 className="label">
                  Commander
                  <span className="chip chip-tag">
                    {selectedCommanderName && selectedCommanderName === deck.commander ? "Your pick" : "Recommended"}
                  </span>
                </h3>
                <ul className="card-list deck-commander">
                  <DeckCardRow card={{ name: deck.commander, quantity: 1 }} quantityLabel="Commander" note={notes.get(deck.commander)} onOpen={onOpenCard} />
                </ul>
              </>
            ) : null}
            {deck.sideboard.length ? (
              <>
                <h3 className="label">
                  Sideboard
                  <span className="muted label-count">{cardCount(deck.sideboard)} cards</span>
                </h3>
                <GroupedDeckList cards={deck.sideboard} typeMap={deck.card_types} suffix="sideboard" notes={notes} onOpenCard={onOpenCard} />
              </>
            ) : !deck.commander ? (
              <>
                <h3 className="label">Sideboard</h3>
                <p className="muted">{isBo1 ? "Best-of-one: no sideboard." : "No sideboard for this list."}</p>
              </>
            ) : null}
          </div>
        </div>
        {notes.size ? <p className="muted field-help deck-why-hint">Tap “Why?” next to a card to see why it made the list.</p> : null}
      </section>

      {!expertMode ? <HowToPlay deck={deck} onOpenCard={onOpenCard} /> : null}

      <DeckExplanationTabs deck={deck} showGamePlanTab={expertMode} onOpenCard={onOpenCard} />

      {deck.role_summary.length || deck.mana_curve.length || deck.color_sources?.length ? (
        <section className="panel results-card" aria-labelledby="structure-heading">
          <h3 id="structure-heading" className="label">Structure</h3>
          <div className="structure-grid">
            <ManaCurveChart points={deck.mana_curve} />
            <ColorSourceChart points={deck.color_sources ?? []} />
            {deck.role_summary.length ? (
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
            ) : null}
          </div>
        </section>
      ) : null}

      <AlternativesPanel alternatives={deck.alternatives ?? []} loading={loading} onBuild={onBuildAlternative} onOpenCard={onOpenCard} />

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

      <section className="panel results-card" aria-labelledby="refine-heading">
        <div className="field-label-row">
          <label id="refine-heading" className="label" htmlFor="refine">Refine Deck</label>
          <span className={`muted field-count ${refinePrompt.length > MAX_PROMPT_CHARS * 0.8 ? "warn" : ""}`}>
            {refinePrompt.length}/{MAX_PROMPT_CHARS}
          </span>
        </div>
        <textarea
          id="refine"
          className="textarea"
          value={refinePrompt}
          maxLength={MAX_PROMPT_CHARS}
          onChange={(event) => onRefinePromptChange(event.target.value)}
          placeholder="e.g. Make it cheaper without losing pressure, or add 4x Counterspell."
        />
        <button type="button" className="button secondary" onClick={startRefine} disabled={loading || !refinePrompt.trim()} style={{ marginTop: 12 }}>
          Apply Refinement
        </button>
        {changes ? (
          <div className="refine-changes">
            <DeckDiffView diff={changes} title="What changed" />
          </div>
        ) : null}
      </section>

      <RevisionHistory revisions={revisions} loading={loading} onUndo={onUndo} onRestore={onRestore} />

      <DeckChat
        bubbles={chat.bubbles}
        sending={chat.sending}
        error={chat.error}
        refining={loading}
        onSend={(message) => void chat.send(deck, message)}
        onApplyRefinement={(bubbleId, refinement) => {
          onRefinePromptChange(refinement);
          setPendingApply({ bubbleId, refinement });
        }}
        onEditRefinement={onRefinePromptChange}
        onClear={resetChat}
      />

      <ShopDeckPanel deck={deck} />

      <ExportPanel deck={deck} />

      {deck.selected_archetype && expertMode ? (
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
        <section className="panel results-card" aria-labelledby="meta-heading">
          <h3 id="meta-heading" className="label">Format Meta Snapshot</h3>
          {meta.as_of ? <p className="muted field-help">Latest event in the corpus: {meta.as_of}.</p> : null}
          <ul className="card-list">
            {meta.archetypes.slice(0, 5).map((archetype) => (
              <li key={archetype.id} className="card-row meta-row">
                <span>
                  {archetype.name}
                  {archetype.metadata?.evidence === "template" ? <span className="chip chip-tag">template</span> : null}
                  {archetype.tags?.slice(0, 2).map((tag) => (
                    <span key={tag} className="chip chip-tag">{tag}</span>
                  ))}
                </span>
                <span className="muted">
                  {archetype.source_count} decks
                  {archetype.avg_placement ? ` • avg ${archetype.avg_placement.toFixed(1)}` : ""}
                  {archetype.metadata?.last_seen ? ` • seen ${archetype.metadata.last_seen}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : metaError ? (
        <p className="muted panel results-card">Meta snapshot unavailable: {metaError}</p>
      ) : null}
    </>
  );
}
