"use client";

import { useState } from "react";

import { useCardSearch } from "@/hooks/use-card-search";
import type { CardRef, FormatName } from "@/lib/types";

export type ManualZone = "mainboard" | "sideboard";

type Props = {
  format: FormatName;
  manualMainboard: CardRef[];
  manualSideboard: CardRef[];
  manualCommander: string;
  manualNotes: string;
  loading: boolean;
  deepAnalysis: boolean;
  onDeepAnalysisChange: (value: boolean) => void;
  onCommanderChange: (value: string) => void;
  onNotesChange: (value: string) => void;
  onAddCard: (name: string, zone: ManualZone) => void;
  onChangeQuantity: (name: string, zone: ManualZone, quantity: number) => void;
  onMoveCard: (name: string, from: ManualZone) => void;
  onClearDraft: () => void;
  onAnalyze: () => void;
  onOpenCard: (name: string) => void;
};

export function AnalyzeForm(props: Props) {
  const {
    format,
    manualMainboard,
    manualSideboard,
    manualCommander,
    manualNotes,
    loading,
    deepAnalysis,
    onDeepAnalysisChange,
    onCommanderChange,
    onNotesChange,
    onAddCard,
    onChangeQuantity,
    onMoveCard,
    onClearDraft,
    onAnalyze,
    onOpenCard
  } = props;

  const [manualQuery, setManualQuery] = useState("");
  const [manualSearchIndex, setManualSearchIndex] = useState(0);
  const [manualTarget, setManualTarget] = useState<ManualZone>("mainboard");
  const { results: manualSearchResults, loading: manualSearchLoading } = useCardSearch(manualQuery, format, true);

  const mainboardCount = manualMainboard.reduce((sum, item) => sum + item.quantity, 0);
  const sideboardCount = manualSideboard.reduce((sum, item) => sum + item.quantity, 0);

  function renderEditable(card: CardRef, zone: ManualZone) {
    return (
      <li key={`${zone}-${card.name}`} className="card-row">
        <button type="button" className="card-button" onClick={() => onOpenCard(card.name)} style={{ flex: 1, textAlign: "left" }}>
          <span>{card.name}</span>
          <span className="muted">{zone}</span>
        </button>
        <button type="button" className="chip" onClick={() => onChangeQuantity(card.name, zone, card.quantity - 1)}>-1</button>
        <input
          className="input"
          type="number"
          min={0}
          max={format === "commander" ? 1 : 20}
          value={card.quantity}
          onChange={(event) => onChangeQuantity(card.name, zone, Number(event.target.value))}
          style={{ width: 76 }}
        />
        <button type="button" className="chip" onClick={() => onChangeQuantity(card.name, zone, card.quantity + 1)}>+1</button>
        {format !== "commander" ? (
          <button type="button" className="chip" onClick={() => onMoveCard(card.name, zone)}>
            {zone === "mainboard" ? "To Side" : "To Main"}
          </button>
        ) : null}
        <button type="button" className="chip" onClick={() => onChangeQuantity(card.name, zone, 0)}>Remove</button>
      </li>
    );
  }

  return (
    <>
      {format === "commander" ? (
        <div className="panel form-card">
          <label className="label" htmlFor="manual-commander">Commander</label>
          <input
            id="manual-commander"
            className="input"
            value={manualCommander}
            onChange={(event) => onCommanderChange(event.target.value)}
            placeholder="Choose or type a legal commander"
          />
        </div>
      ) : null}

      <div className="panel form-card">
        <div className="export-row" style={{ alignItems: "center" }}>
          <label className="label" htmlFor="manual-card-search" style={{ marginBottom: 0 }}>Add Cards</label>
          {format !== "commander" ? (
            <select className="select" value={manualTarget} onChange={(event) => setManualTarget(event.target.value as ManualZone)}>
              <option value="mainboard">Mainboard</option>
              <option value="sideboard">Sideboard</option>
            </select>
          ) : null}
        </div>
        <input
          id="manual-card-search"
          className="input"
          value={manualQuery}
          onChange={(event) => {
            setManualQuery(event.target.value);
            setManualSearchIndex(0);
          }}
          onKeyDown={(event) => {
            if (!manualSearchResults.length) return;
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setManualSearchIndex((current) => Math.min(current + 1, manualSearchResults.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setManualSearchIndex((current) => Math.max(current - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              const card = manualSearchResults[manualSearchIndex];
              if (card) onAddCard(card.name, manualTarget);
            }
          }}
          placeholder="Search cards by name"
        />
        <p className="muted" style={{ marginTop: 8 }}>Use ↑/↓ to choose a result and Enter to add it.</p>
        <div className="card-list" style={{ marginTop: 12, maxHeight: 260, overflowY: "auto" }}>
          {manualSearchLoading ? <p className="muted">Searching cards...</p> : null}
          {!manualSearchLoading && manualQuery.trim().length >= 2 && !manualSearchResults.length ? <p className="muted">No cards matched your search.</p> : null}
          {manualSearchResults.map((card, index) => (
            <li key={`search-${card.name}`} className={`card-row ${index === manualSearchIndex ? "active" : ""}`}>
              <button type="button" className="card-button" onClick={() => onOpenCard(card.name)} style={{ flex: 1, textAlign: "left" }}>
                <span>{card.name}</span>
                <span className="muted">{card.mana_cost ? `${card.mana_cost} • ` : ""}{card.type_line}</span>
              </button>
              <button type="button" className="chip" onClick={() => onAddCard(card.name, "mainboard")}>Main</button>
              {format !== "commander" ? (
                <button type="button" className="chip" onClick={() => onAddCard(card.name, "sideboard")}>Side</button>
              ) : null}
            </li>
          ))}
        </div>
      </div>

      <div className="panel form-card">
        <div className="export-row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="button secondary" onClick={onClearDraft}>Clear Draft</button>
        </div>
      </div>

      <div className="panel form-card">
        <div className="label">Mainboard ({mainboardCount})</div>
        <ul className="card-list">
          {manualMainboard.map((card) => renderEditable(card, "mainboard"))}
          {!manualMainboard.length ? <li className="card-row"><span className="muted">Add cards to begin building.</span></li> : null}
        </ul>
      </div>

      {format !== "commander" ? (
        <div className="panel form-card">
          <div className="label">Sideboard ({sideboardCount})</div>
          <ul className="card-list">
            {manualSideboard.map((card) => renderEditable(card, "sideboard"))}
            {!manualSideboard.length ? <li className="card-row"><span className="muted">Optional sideboard cards go here.</span></li> : null}
          </ul>
        </div>
      ) : null}

      <div className="panel form-card">
        <label className="label" htmlFor="manual-notes">Notes</label>
        <textarea id="manual-notes" className="textarea" value={manualNotes} onChange={(event) => onNotesChange(event.target.value)} />
      </div>

      <div className="panel form-card" style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: "0.9rem" }}>
          <input
            type="checkbox"
            checked={deepAnalysis}
            onChange={(event) => onDeepAnalysisChange(event.target.checked)}
            style={{ accentColor: "var(--accent-2, #38bdf8)", width: 16, height: 16 }}
          />
          Deep analysis (Claude coaching)
        </label>
        <span className="muted" style={{ fontSize: "0.8rem" }}>
          {deepAnalysis ? "Adds an LLM-written game plan and coaching note." : "Faster, fully heuristic — no LLM call."}
        </span>
      </div>

      <button type="button" className="button" onClick={onAnalyze} disabled={loading}>
        {loading ? "Analyzing deck..." : "Analyze My Deck"}
      </button>
    </>
  );
}
