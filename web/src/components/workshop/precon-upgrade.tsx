"use client";

import { useEffect, useState, type FormEvent } from "react";

import { fetchPrecons, upgradePrecon } from "@/lib/api";
import { AFFILIATE_DISCLOSURE } from "@/lib/affiliate";
import type { PreconSummary, PreconUpgradeResponse } from "@/lib/types";

type Props = {
  onOpenCard: (name: string) => void;
};

const BRACKETS = [
  { value: 2, label: "2 — Precon" },
  { value: 3, label: "3 — Upgraded" },
  { value: 4, label: "4 — Optimized" }
];

function money(value: number): string {
  return `$${value.toFixed(2)}`;
}

export function PreconUpgrade({ onOpenCard }: Props) {
  const [query, setQuery] = useState("");
  const [precons, setPrecons] = useState<PreconSummary[]>([]);
  const [searchError, setSearchError] = useState("");
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<PreconSummary | null>(null);
  const [deckText, setDeckText] = useState("");
  const [budget, setBudget] = useState("50");
  const [maxBracket, setMaxBracket] = useState(3);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<PreconUpgradeResponse | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const handle = setTimeout(() => {
      setSearching(true);
      fetchPrecons(query, 8, controller.signal)
        .then((rows) => {
          setPrecons(rows);
          setSearchError("");
        })
        .catch((err: unknown) => {
          if (err instanceof DOMException && err.name === "AbortError") return;
          setSearchError(err instanceof Error ? err.message : "Precon search failed");
        })
        .finally(() => {
          if (!controller.signal.aborted) setSearching(false);
        });
    }, 200);
    return () => {
      clearTimeout(handle);
      controller.abort();
    };
  }, [query]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const budgetUsd = Number(budget);
    if (!Number.isFinite(budgetUsd) || budgetUsd < 0 || budgetUsd > 5000) {
      setError("Enter a budget from $0 to $5000.");
      return;
    }
    const text = deckText.trim();
    if (!text && !selected) {
      setError("Pick a precon or paste a decklist.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const upgraded = await upgradePrecon({
        budget_usd: budgetUsd,
        max_bracket: maxBracket,
        ...(text ? { deck_text: text } : { precon_id: selected?.id })
      });
      setResult(upgraded);
    } catch (err: unknown) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Precon upgrade failed");
    } finally {
      setLoading(false);
    }
  }

  const pasted = deckText.trim().length > 0;

  return (
    <form className="precon-upgrade" onSubmit={onSubmit}>
      <div className="panel form-card panel-strong">
        <span className="label">Upgrade a precon</span>
        <p className="muted">
          Pick an official Commander precon or paste your list, set a budget, and get one-for-one swaps that stay inside it.
          Basics and the commander stay. Prices are the stored market prices, and the cart is only the cards you add.
        </p>
      </div>

      <div className="panel form-card">
        <label className="label" htmlFor="precon-search">Find a precon</label>
        <input
          id="precon-search"
          className="input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search by deck or commander, such as Elven Empire"
          autoComplete="off"
        />
        <div className="card-list" style={{ marginTop: 12 }} role="listbox" aria-label="Matching precons">
          {searching ? <p className="muted">Looking up precons...</p> : null}
          {searchError ? <p className="workflow-error" role="alert">{searchError}</p> : null}
          {!searching && !precons.length ? <p className="muted">No precons matched that search.</p> : null}
          {precons.map((precon) => {
            const active = selected?.id === precon.id;
            return (
              <button
                key={precon.id}
                type="button"
                role="option"
                aria-selected={active}
                className={`card-button ${active ? "active" : ""}`}
                onClick={() => setSelected(precon)}
              >
                <span>
                  <strong>{precon.name}</strong>
                  {precon.commander ? <span className="muted"> — {precon.commander}</span> : null}
                </span>
                <span className="muted">{precon.release_date?.slice(0, 4) ?? precon.set_code}</span>
              </button>
            );
          })}
        </div>
        {selected ? (
          <p className="muted" style={{ marginTop: 12 }}>
            Selected: {selected.name}
            {selected.commander ? ` (${selected.commander})` : ""}.{" "}
            <button type="button" className="chip chip-small" onClick={() => setSelected(null)}>Clear</button>
          </p>
        ) : null}
      </div>

      <div className="panel form-card">
        <label className="label" htmlFor="precon-list">Or paste a decklist</label>
        <textarea
          id="precon-list"
          className="input"
          rows={8}
          value={deckText}
          onChange={(event) => setDeckText(event.target.value)}
          placeholder={"Commander\n1 Krenko, Mob Boss\nDeck\n1 Sol Ring\n..."}
        />
        {pasted && selected ? (
          <p className="muted">The pasted list is what gets upgraded. Clear it to use {selected.name}.</p>
        ) : null}
      </div>

      <div className="panel form-card precon-budget-row">
        <div>
          <label className="label" htmlFor="precon-budget">Budget (USD)</label>
          <input
            id="precon-budget"
            className="input"
            type="number"
            inputMode="decimal"
            min={0}
            max={5000}
            step="1"
            value={budget}
            onChange={(event) => setBudget(event.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="precon-bracket">Bracket ceiling</label>
          <select
            id="precon-bracket"
            className="select"
            value={maxBracket}
            onChange={(event) => setMaxBracket(Number(event.target.value))}
          >
            {BRACKETS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <p className="muted">Adds stay at or under this bracket. 3 allows a few Game Changers and blocks mass land denial and extra turns.</p>
        </div>
      </div>

      {error ? <p className="workflow-error" role="alert">{error}</p> : null}
      <button className="button" type="submit" disabled={loading}>
        {loading ? "Finding swaps..." : "Show upgrades"}
      </button>

      {result ? <PreconResult result={result} onOpenCard={onOpenCard} /> : null}
    </form>
  );
}

function PreconResult({
  result,
  onOpenCard
}: {
  result: PreconUpgradeResponse;
  onOpenCard: (name: string) => void;
}) {
  const legal = result.legality.is_legal;
  return (
    <section className="panel form-card" aria-live="polite">
      <span className="label">{result.name}</span>
      <p>
        {result.commander ? <>Commander: <button type="button" className="card-button" onClick={() => onOpenCard(result.commander!)}>{result.commander}</button></> : "No commander"}
      </p>
      <div className="chips">
        <span className="chip">{money(result.total_cost_usd)} of {money(result.budget_usd)}</span>
        <span className={`chip ${legal ? "active" : ""}`}>{legal ? "Commander legal" : "Not legal"}</span>
        <span className="chip">Bracket {result.bracket.estimated}{result.bracket.target ? ` (ceiling ${result.bracket.target})` : ""}</span>
      </div>
      {!legal && result.legality.errors.length ? (
        <ul className="precon-notes">
          {result.legality.errors.map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : null}
      {result.warnings.length ? (
        <ul className="precon-notes">
          {result.warnings.map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : null}
      {result.bracket.notes.length ? <p className="muted">{result.bracket.notes[0]}</p> : null}

      {result.swaps.length ? (
        <ol className="precon-swaps">
          {result.swaps.map((swap) => (
            <li key={`${swap.rank}-${swap.add}`} className="precon-swap">
              <div className="precon-swap-head">
                <span className="chip chip-small">#{swap.rank}</span>
                <button type="button" className="card-button" onClick={() => onOpenCard(swap.cut)}>{swap.cut}</button>
                <span aria-hidden="true">→</span>
                <button type="button" className="card-button" onClick={() => onOpenCard(swap.add)}>{swap.add}</button>
                <span className="muted">{money(swap.add_price_usd)}</span>
              </div>
              <p>{swap.cut_explanation}</p>
              <p>{swap.add_explanation}</p>
            </li>
          ))}
        </ol>
      ) : (
        <p>No swap improved this deck inside the budget.</p>
      )}

      {result.tcgplayer_cart_url ? (
        <p>
          <a className="button" href={result.tcgplayer_cart_url} target="_blank" rel="noreferrer">
            Buy the adds on TCGplayer
          </a>
        </p>
      ) : null}
      <p className="muted" style={{ fontSize: "0.75rem" }}>{AFFILIATE_DISCLOSURE}</p>
    </section>
  );
}
