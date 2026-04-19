"use client";

import { useEffect, useRef, useState } from "react";

import type {
  ArchetypePackage,
  CardSearchResponse,
  CardSearchResult,
  CardDetailResponse,
  CardRecord,
  CardRef,
  CommanderProfile,
  CommanderProfileResponse,
  CommanderSearchResponse,
  CommanderSearchResult,
  DataStatusResponse,
  DeckAnalysisResponse,
  DeckResponse,
  FormatName,
  MetaSummaryResponse,
  ParsedDecklistResponse
} from "@/lib/types";

const COLORS = ["W", "U", "B", "R", "G", "C"];
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

const STRATEGY_OPTIONS = [
  {
    id: "aggro",
    label: "Aggro",
    description: "Fast pressure with low-curve threats and efficient damage.",
    playstyleTags: ["aggro"],
    themeTags: []
  },
  {
    id: "control",
    label: "Control",
    description: "Trade resources early, then win with inevitability.",
    playstyleTags: ["control", "interaction"],
    themeTags: []
  },
  {
    id: "midrange",
    label: "Midrange",
    description: "Flexible threats and interaction aimed at stabilizing and pivoting.",
    playstyleTags: ["midrange"],
    themeTags: []
  },
  {
    id: "combo",
    label: "Combo",
    description: "Assemble a compact engine or finish that ends the game quickly.",
    playstyleTags: ["combo"],
    themeTags: []
  },
  {
    id: "tempo",
    label: "Tempo",
    description: "Protect a small lead with cheap interaction and efficient pressure.",
    playstyleTags: ["tempo", "spells", "aggro"],
    themeTags: []
  },
  {
    id: "ramp",
    label: "Ramp",
    description: "Accelerate mana to deploy stronger threats ahead of schedule.",
    playstyleTags: ["ramp"],
    themeTags: []
  },
  {
    id: "spellslinger",
    label: "Spellslinger",
    description: "High spell density with payoffs for casting instants and sorceries.",
    playstyleTags: ["spells", "prowess", "tempo"],
    themeTags: []
  },
  {
    id: "tokens",
    label: "Tokens",
    description: "Go wide with scalable boards and anthem-style payoffs.",
    playstyleTags: ["tokens"],
    themeTags: ["tokens"]
  },
  {
    id: "tribal",
    label: "Tribal",
    description: "Synergy built around a creature type or tribe-specific payoffs.",
    playstyleTags: ["tribal"],
    themeTags: ["tribal", "slivers"]
  },
  {
    id: "lifegain",
    label: "Lifegain",
    description: "Snowball value from recurring life gain and payoff creatures.",
    playstyleTags: ["lifegain"],
    themeTags: ["lifegain"]
  },
  {
    id: "sacrifice",
    label: "Sacrifice",
    description: "Convert creatures or tokens into cards, damage, or board control.",
    playstyleTags: ["sacrifice", "combo"],
    themeTags: ["sacrifice"]
  },
  {
    id: "reanimator",
    label: "Reanimator",
    description: "Load the graveyard and cheat high-impact threats back into play.",
    playstyleTags: ["reanimator", "midrange"],
    themeTags: ["graveyard"]
  }
] as const;

type StrategyId = (typeof STRATEGY_OPTIONS)[number]["id"];
type ExportTarget = "arena" | "plain" | "csv" | "moxfield";
type CommanderMode = "recommend" | "selected";
type CommanderSort = "match" | "popularity" | "support" | "name";
type BuilderMode = "generate" | "analyze";
type ManualZone = "mainboard" | "sideboard";
const MANUAL_DRAFT_STORAGE_KEY = "mtg-deck-builder-manual-draft";

function uniqueValues(values: string[]) {
  return [...new Set(values)];
}

function parseBudgetInput(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }

  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return undefined;
  }

  return parsed;
}

export function DeckWorkshop() {
  const [builderMode, setBuilderMode] = useState<BuilderMode>("generate");
  const [format, setFormat] = useState<FormatName>("modern");
  const [colors, setColors] = useState<string[]>(["U", "R"]);
  const [selectedStrategies, setSelectedStrategies] = useState<StrategyId[]>(["aggro", "spellslinger"]);
  const [budget, setBudget] = useState("400");
  const [prompt, setPrompt] = useState("Build me a strong Modern prowess deck that feels explosive and is still friendly to a newer player.");
  const [deck, setDeck] = useState<DeckResponse | null>(null);
  const [meta, setMeta] = useState<MetaSummaryResponse | null>(null);
  const [refinePrompt, setRefinePrompt] = useState("Make it a bit cheaper without losing too much pressure.");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedCard, setSelectedCard] = useState<CardRecord | null>(null);
  const [cardLoading, setCardLoading] = useState(false);
  const [cardError, setCardError] = useState<string | null>(null);
  const [exportTarget, setExportTarget] = useState<ExportTarget>("plain");
  const [exportContent, setExportContent] = useState("");
  const [exportLoading, setExportLoading] = useState(false);
  const [dataStatus, setDataStatus] = useState<DataStatusResponse | null>(null);
  const [commanderMode, setCommanderMode] = useState<CommanderMode>("recommend");
  const [commanderSort, setCommanderSort] = useState<CommanderSort>("match");
  const [commanderSearch, setCommanderSearch] = useState("");
  const [commanders, setCommanders] = useState<CommanderSearchResult[]>([]);
  const [commanderLoading, setCommanderLoading] = useState(false);
  const [selectedCommanderName, setSelectedCommanderName] = useState("");
  const [selectedCommanderProfile, setSelectedCommanderProfile] = useState<CommanderProfile | null>(null);
  const [manualMainboard, setManualMainboard] = useState<CardRef[]>([]);
  const [manualSideboard, setManualSideboard] = useState<CardRef[]>([]);
  const [manualCommander, setManualCommander] = useState("");
  const [manualNotes, setManualNotes] = useState("Tell me how this deck plays, what shell it resembles, and what I should improve.");
  const [manualQuery, setManualQuery] = useState("");
  const [manualSearchResults, setManualSearchResults] = useState<CardSearchResult[]>([]);
  const [manualSearchLoading, setManualSearchLoading] = useState(false);
  const [manualTarget, setManualTarget] = useState<ManualZone>("mainboard");
  const [analysis, setAnalysis] = useState<DeckAnalysisResponse | null>(null);
  const [manualImportText, setManualImportText] = useState("");
  const [manualSearchIndex, setManualSearchIndex] = useState(0);

  const generateAbortRef = useRef<AbortController | null>(null);
  const refineAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      generateAbortRef.current?.abort();
      refineAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    async function fetchDataStatus() {
      try {
        const response = await fetch(`${API_BASE}/api/data-status`);
        if (!response.ok) {
          return;
        }
        const payload = (await response.json()) as DataStatusResponse;
        setDataStatus(payload);
      } catch {
        // Best-effort status only.
      }
    }

    void fetchDataStatus();
  }, []);

  useEffect(() => {
    if (!selectedCard) {
      return undefined;
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelectedCard(null);
        setCardError(null);
      }
    }

    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [selectedCard]);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(MANUAL_DRAFT_STORAGE_KEY);
      if (!raw) {
        return;
      }
      const parsed = JSON.parse(raw) as {
        format?: FormatName;
        mainboard?: CardRef[];
        sideboard?: CardRef[];
        commander?: string;
        notes?: string;
      };
      if (parsed.format) {
        setFormat(parsed.format);
      }
      setManualMainboard(parsed.mainboard ?? []);
      setManualSideboard(parsed.sideboard ?? []);
      setManualCommander(parsed.commander ?? "");
      setManualNotes(parsed.notes ?? "Tell me how this deck plays, what shell it resembles, and what I should improve.");
    } catch {
      // ignore local draft parse failures
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem(
      MANUAL_DRAFT_STORAGE_KEY,
      JSON.stringify({
        format,
        mainboard: manualMainboard,
        sideboard: manualSideboard,
        commander: manualCommander,
        notes: manualNotes
      })
    );
  }, [format, manualCommander, manualMainboard, manualNotes, manualSideboard]);

  useEffect(() => {
    if (format !== "commander") {
      setCommanders([]);
      setSelectedCommanderProfile(null);
      setSelectedCommanderName("");
      return;
    }

    const activeStrategies = STRATEGY_OPTIONS.filter((option) => selectedStrategies.includes(option.id));
    const playstyleTags = uniqueValues(activeStrategies.flatMap((option) => option.playstyleTags));
    const themeTags = uniqueValues(activeStrategies.flatMap((option) => option.themeTags));

    const controller = new AbortController();

    async function fetchCommanders() {
      setCommanderLoading(true);
      try {
        const params = new URLSearchParams();
        if (colors.length) params.set("colors", colors.join(","));
        if (playstyleTags.length) params.set("playstyle_tags", playstyleTags.join(","));
        if (themeTags.length) params.set("theme_tags", themeTags.join(","));
        if (commanderSearch.trim()) params.set("search", commanderSearch.trim());
        params.set("sort", commanderSort);
        params.set("limit", "18");
        const response = await fetch(`${API_BASE}/v1/commanders?${params.toString()}`, { signal: controller.signal });
        if (!response.ok) {
          return;
        }
        const payload = (await response.json()) as CommanderSearchResponse;
        setCommanders(payload.commanders);
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return;
      } finally {
        setCommanderLoading(false);
      }
    }

    void fetchCommanders();
    return () => controller.abort();
  }, [colors, commanderSearch, commanderSort, format, selectedStrategies]);

  useEffect(() => {
    if (format !== "commander" || !selectedCommanderName) {
      return;
    }

    async function fetchCommanderProfile() {
      const response = await fetch(`${API_BASE}/v1/commanders/${encodeURIComponent(selectedCommanderName)}`);
      if (!response.ok) {
        return;
      }
      const payload = (await response.json()) as CommanderProfileResponse;
      setSelectedCommanderProfile(payload.commander);
      if (payload.commander.colors.length) {
        setColors(payload.commander.colors);
      }
    }

    void fetchCommanderProfile();
  }, [format, selectedCommanderName]);

  useEffect(() => {
    if (builderMode !== "analyze" || manualQuery.trim().length < 2) {
      setManualSearchResults([]);
      setManualSearchIndex(0);
      return;
    }

    const controller = new AbortController();
    async function fetchCards() {
      setManualSearchLoading(true);
      try {
        const params = new URLSearchParams({
          query: manualQuery.trim(),
          format
        });
        const response = await fetch(`${API_BASE}/v1/cards?${params.toString()}`, {
          signal: controller.signal
        });
        if (!response.ok) {
          return;
        }
        const payload = (await response.json()) as CardSearchResponse;
        setManualSearchResults(payload.cards);
        setManualSearchIndex(0);
      } catch {
        // Best-effort search.
      } finally {
        setManualSearchLoading(false);
      }
    }

    void fetchCards();
    return () => controller.abort();
  }, [builderMode, format, manualQuery]);

  // Reset keyboard-nav index whenever results list changes to prevent stale index.
  useEffect(() => { setManualSearchIndex(0); }, [manualSearchResults]);

  const toggleValue = (value: string, values: string[], setValues: (next: string[]) => void) => {
    if (values.includes(value)) {
      setValues(values.filter((item) => item !== value));
      return;
    }
    setValues([...values, value]);
  };

  function updateManualList(zone: ManualZone, updater: (cards: CardRef[]) => CardRef[]) {
    if (zone === "mainboard") {
      setManualMainboard((current) => updater(current));
      return;
    }
    setManualSideboard((current) => updater(current));
  }

  function addManualCard(cardName: string, zone: ManualZone) {
    updateManualList(zone, (cards) => {
      const existing = cards.find((item) => item.name === cardName);
      if (existing) {
        return cards.map((item) => item.name === cardName ? { ...item, quantity: item.quantity + 1 } : item);
      }
      return [...cards, { name: cardName, quantity: 1 }];
    });
  }

  function setManualQuantity(cardName: string, zone: ManualZone, quantity: number) {
    updateManualList(zone, (cards) => {
      if (quantity <= 0) {
        return cards.filter((item) => item.name !== cardName);
      }
      return cards.map((item) => item.name === cardName ? { ...item, quantity } : item);
    });
  }

  const mainboardCount = manualMainboard.reduce((sum, item) => sum + item.quantity, 0);
  const sideboardCount = manualSideboard.reduce((sum, item) => sum + item.quantity, 0);

  function moveManualCard(cardName: string, from: ManualZone) {
    const fromCards = from === "mainboard" ? manualMainboard : manualSideboard;
    const card = fromCards.find((item) => item.name === cardName);
    if (!card) return;
    setManualQuantity(cardName, from, 0);
    addManualCard(cardName, from === "mainboard" ? "sideboard" : "mainboard");
  }

  async function openCard(name: string) {
    setCardLoading(true);
    setCardError(null);

    try {
      const localResponse = await fetch(`${API_BASE}/v1/cards/${encodeURIComponent(name)}`);
      if (!localResponse.ok) {
        throw new Error("Could not load card details.");
      }
      const payload = (await localResponse.json()) as CardDetailResponse;
      if (!payload.card.image_uri && !payload.card.faces.some((face) => face.image_uri)) {
        setCardError("No card image was available for this card.");
      }
      setSelectedCard(payload.card);
    } catch (fetchError) {
      setCardError(fetchError instanceof Error ? fetchError.message : "Could not load card details.");
      setSelectedCard({
        oracle_id: null,
        scryfall_id: null,
        name,
        normalized_name: null,
        mana_cost: "",
        mana_value: 0,
        colors: [],
        color_identity: [],
        type_line: "",
        oracle_text: "",
        keywords: [],
        layout: null,
        rarity: null,
        set_code: null,
        released_at: null,
        image_uri: null,
        image_uris: {},
        faces: [],
        price_usd: null,
        price_usd_foil: null,
        legalities: {},
        tags: [],
        purchase_links: {}
      });
    } finally {
      setCardLoading(false);
    }
  }

  async function generateDeck() {
    const parsedBudget = parseBudgetInput(budget);
    if (budget.trim() && parsedBudget === undefined) {
      setError("Budget must be a non-negative number.");
      return;
    }
    if (format === "commander" && commanderMode === "selected" && !selectedCommanderName) {
      setError("Select a commander before building a commander deck from an explicit commander.");
      return;
    }

    generateAbortRef.current?.abort();
    const controller = new AbortController();
    generateAbortRef.current = controller;

    setLoading(true);
    setError(null);
    setExportContent("");

    const activeStrategies = STRATEGY_OPTIONS.filter((option) => selectedStrategies.includes(option.id));
    const playstyleTags = uniqueValues(activeStrategies.flatMap((option) => option.playstyleTags));
    const themeTags = uniqueValues(activeStrategies.flatMap((option) => option.themeTags));

    try {
      const response = await fetch(`${API_BASE}/v1/decks/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          format,
          colors,
          commander_name: format === "commander" && commanderMode === "selected" ? selectedCommanderName || undefined : undefined,
          playstyle_tags: playstyleTags,
          theme_tags: themeTags,
          budget: parsedBudget,
          mode: "constraint-aware",
          experience_level: "beginner",
          prompt
        })
      });
      if (!response.ok) {
        throw new Error("Generation failed");
      }
      const payload = (await response.json()) as DeckResponse;
      setDeck(payload);
      setAnalysis(null);
      const metaResponse = await fetch(`${API_BASE}/v1/meta/summary?format=${format}`, { signal: controller.signal });
      if (metaResponse.ok) {
        const metaPayload = (await metaResponse.json()) as MetaSummaryResponse;
        setMeta(metaPayload);
      }
    } catch (generationError) {
      if (generationError instanceof Error && generationError.name === "AbortError") return;
      setError(generationError instanceof Error ? generationError.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  async function analyzeManualDeck() {
    setLoading(true);
    setError(null);
    setExportContent("");
    try {
      const response = await fetch(`${API_BASE}/v1/decks/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          format,
          commander: format === "commander" ? manualCommander || undefined : undefined,
          mainboard: manualMainboard,
          sideboard: format === "commander" ? [] : manualSideboard,
          notes: manualNotes
        })
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Analysis failed");
      }
      const payload = (await response.json()) as DeckAnalysisResponse;
      setAnalysis(payload);
      setDeck(null);
      setMeta(null);
    } catch (analysisError) {
      setError(analysisError instanceof Error ? analysisError.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  async function importManualDeck() {
    if (!manualImportText.trim()) {
      setError("Paste a deck list before importing.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/decks/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          format,
          deck_text: manualImportText
        })
      });
      if (!response.ok) {
        throw new Error("Deck import failed");
      }
      const payload = (await response.json()) as ParsedDecklistResponse;
      setManualMainboard(payload.mainboard);
      setManualSideboard(payload.sideboard);
      setManualCommander(payload.commander ?? "");
      if (payload.warnings.length) {
        setError(payload.warnings.join(" "));
      }
    } catch (importError) {
      setError(importError instanceof Error ? importError.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  function renderPackageList(title: string, packages: ArchetypePackage[]) {
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

  function renderDeckCard(card: CardRef, suffix: string, quantityLabel: string) {
    return (
      <li key={`${card.name}-${card.quantity}-${suffix}`} className="card-row card-row-action">
        <button type="button" className="card-button" onClick={() => void openCard(card.name)}>
          <span>{card.name}</span>
          <span className="muted">{quantityLabel}</span>
        </button>
      </li>
    );
  }

  function renderEditableManualCard(card: CardRef, zone: ManualZone) {
    return (
      <li key={`${zone}-${card.name}`} className="card-row">
        <button type="button" className="card-button" onClick={() => void openCard(card.name)} style={{ flex: 1, textAlign: "left" }}>
          <span>{card.name}</span>
          <span className="muted">{zone}</span>
        </button>
        <button type="button" className="chip" onClick={() => setManualQuantity(card.name, zone, card.quantity - 1)}>-1</button>
        <input
          className="input"
          type="number"
          min={0}
          max={format === "commander" ? 1 : 20}
          value={card.quantity}
          onChange={(event) => setManualQuantity(card.name, zone, Number(event.target.value))}
          style={{ width: 76 }}
        />
        <button type="button" className="chip" onClick={() => setManualQuantity(card.name, zone, card.quantity + 1)}>+1</button>
        {format !== "commander" ? (
          <button type="button" className="chip" onClick={() => moveManualCard(card.name, zone)}>
            {zone === "mainboard" ? "To Side" : "To Main"}
          </button>
        ) : null}
        <button type="button" className="chip" onClick={() => setManualQuantity(card.name, zone, 0)}>Remove</button>
      </li>
    );
  }

  async function refineDeck() {
    if (!deck) return;
    refineAbortRef.current?.abort();
    const controller = new AbortController();
    refineAbortRef.current = controller;
    setLoading(true);
    setError(null);
    setExportContent("");
    try {
      const response = await fetch(`${API_BASE}/v1/decks/refine`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          deck,
          refinement_prompt: refinePrompt
        })
      });
      if (!response.ok) {
        throw new Error("Refinement failed");
      }
      const payload = (await response.json()) as DeckResponse;
      setDeck(payload);
    } catch (refinementError) {
      if (refinementError instanceof Error && refinementError.name === "AbortError") return;
      setError(refinementError instanceof Error ? refinementError.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  async function exportDeck() {
    if (!deck) return;

    setExportLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/decks/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          deck,
          target: exportTarget
        })
      });
      if (!response.ok) {
        throw new Error("Export failed");
      }
      const payload = (await response.json()) as { content: string; target: ExportTarget };
      setExportContent(payload.content);
    } catch (exportError) {
      setError(exportError instanceof Error ? exportError.message : "Unknown error");
    } finally {
      setExportLoading(false);
    }
  }

  return (
    <div className="builder">
      <section className="form-grid">
        <div className="panel form-card panel-strong">
          <span className="label">Mode</span>
          <div className="chips">
            <button type="button" className={`chip ${builderMode === "generate" ? "active" : ""}`} onClick={() => setBuilderMode("generate")}>
              Generate
            </button>
            <button type="button" className={`chip ${builderMode === "analyze" ? "active" : ""}`} onClick={() => setBuilderMode("analyze")}>
              Analyze My Deck
            </button>
          </div>
        </div>

        <div className="panel form-card panel-strong">
          <label className="label" htmlFor="format">Format</label>
          <select id="format" className="select" value={format} onChange={(event) => setFormat(event.target.value as FormatName)}>
            <option value="standard">Standard</option>
            <option value="modern">Modern</option>
            <option value="legacy">Legacy</option>
            <option value="commander">Commander</option>
          </select>
        </div>

        <div className="panel form-card">
          <span className="label">Colors</span>
          <div className="chips">
            {COLORS.map((color) => (
              <button
                key={color}
                type="button"
                className={`chip ${colors.includes(color) ? "active" : ""}`}
                onClick={() => toggleValue(color, colors, setColors)}
              >
                {color}
              </button>
            ))}
          </div>
        </div>

        {format === "commander" ? (
          <div className="panel form-card panel-strong">
            <span className="label">Commander Mode</span>
            <div className="chips">
              <button type="button" className={`chip ${commanderMode === "recommend" ? "active" : ""}`} onClick={() => setCommanderMode("recommend")}>
                Recommend Commander
              </button>
              <button type="button" className={`chip ${commanderMode === "selected" ? "active" : ""}`} onClick={() => setCommanderMode("selected")}>
                I&apos;ll Choose
              </button>
            </div>
            <p className="muted" style={{ marginTop: 12 }}>
              Browse ranked commanders, filter them by colors and playstyle, then lock one in for deck generation.
            </p>
          </div>
        ) : null}

        <div className="panel form-card">
          <span className="label">Deck Strategy</span>
          <div className="chips">
            {STRATEGY_OPTIONS.map((option) => (
              <button
                key={option.id}
                type="button"
                className={`chip chip-rich ${selectedStrategies.includes(option.id) ? "active" : ""}`}
                onClick={() => toggleValue(option.id, selectedStrategies, (next) => setSelectedStrategies(next as StrategyId[]))}
              >
                <strong>{option.label}</strong>
                <span>{option.description}</span>
              </button>
            ))}
          </div>
        </div>

        {format === "commander" ? (
          <div className="panel form-card">
            <div className="export-row" style={{ alignItems: "center" }}>
              <label className="label" htmlFor="commander-search" style={{ marginBottom: 0 }}>Commander Search</label>
              <select className="select" value={commanderSort} onChange={(event) => setCommanderSort(event.target.value as CommanderSort)}>
                <option value="match">Best Match</option>
                <option value="popularity">Popularity</option>
                <option value="support">Support Depth</option>
                <option value="name">Name</option>
              </select>
            </div>
            <input
              id="commander-search"
              className="input"
              value={commanderSearch}
              onChange={(event) => setCommanderSearch(event.target.value)}
              placeholder="Search any legal commander"
            />
            <div className="card-list" style={{ marginTop: 12, maxHeight: 340, overflowY: "auto" }}>
              {commanderLoading ? <p className="muted">Ranking commanders...</p> : null}
              {!commanderLoading && !commanders.length ? <p className="muted">No commanders matched the current filters.</p> : null}
              {commanders.map((commander) => (
                <div key={commander.name} className="card-row" style={{ display: "block" }}>
                  <div className="export-row" style={{ alignItems: "center" }}>
                    <button
                      type="button"
                      className={`card-button ${selectedCommanderName === commander.name ? "active" : ""}`}
                      onClick={() => {
                        setSelectedCommanderName(commander.name);
                        setCommanderMode("selected");
                      }}
                      style={{ flex: 1, textAlign: "left" }}
                    >
                      <span>{commander.name}</span>
                      <span className="muted">
                        {commander.colors.join("") || "Colorless"} • support {commander.support_depth} • pop {commander.popularity.toFixed(0)}
                      </span>
                    </button>
                    <button type="button" className="chip" onClick={() => void openCard(commander.name)}>View Card</button>
                  </div>
                  <p className="muted" style={{ marginTop: 8 }}>{commander.strategy_summary}</p>
                  {commander.tags.length ? <p className="muted" style={{ marginTop: 6 }}>Tags: {commander.tags.slice(0, 5).join(", ")}</p> : null}
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {builderMode === "generate" ? (
          <>
            <div className="panel form-card">
              <label className="label" htmlFor="budget">Budget</label>
              <input id="budget" className="input" value={budget} onChange={(event) => setBudget(event.target.value)} />
            </div>

            <div className="panel form-card">
              <label className="label" htmlFor="prompt">Build Brief</label>
              <textarea id="prompt" className="textarea" value={prompt} onChange={(event) => setPrompt(event.target.value)} />
            </div>

            <button type="button" className="button" onClick={generateDeck} disabled={loading}>
              {loading ? "Forging deck..." : "Build My Deck"}
            </button>
          </>
        ) : (
          <>
            {format === "commander" ? (
              <div className="panel form-card">
                <label className="label" htmlFor="manual-commander">Commander</label>
                <input
                  id="manual-commander"
                  className="input"
                  value={manualCommander}
                  onChange={(event) => setManualCommander(event.target.value)}
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
                onChange={(event) => setManualQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (!manualSearchResults.length) {
                    return;
                  }
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    setManualSearchIndex((current) => Math.min(current + 1, manualSearchResults.length - 1));
                  } else if (event.key === "ArrowUp") {
                    event.preventDefault();
                    setManualSearchIndex((current) => Math.max(current - 1, 0));
                  } else if (event.key === "Enter") {
                    event.preventDefault();
                    const card = manualSearchResults[manualSearchIndex];
                    if (card) {
                      addManualCard(card.name, manualTarget);
                    }
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
                    <button type="button" className="card-button" onClick={() => void openCard(card.name)} style={{ flex: 1, textAlign: "left" }}>
                      <span>{card.name}</span>
                      <span className="muted">{card.mana_cost ? `${card.mana_cost} • ` : ""}{card.type_line}</span>
                    </button>
                    <button type="button" className="chip" onClick={() => addManualCard(card.name, "mainboard")}>Main</button>
                    {format !== "commander" ? (
                      <button type="button" className="chip" onClick={() => addManualCard(card.name, "sideboard")}>Side</button>
                    ) : null}
                  </li>
                ))}
              </div>
            </div>

            <div className="panel form-card">
              <label className="label" htmlFor="manual-import">Import Deck Text</label>
              <textarea
                id="manual-import"
                className="textarea"
                value={manualImportText}
                onChange={(event) => setManualImportText(event.target.value)}
                placeholder={"Commander\n1 Aminatou, the Fateshifter\n\nMainboard\n1 Sol Ring\n1 Arcane Signet\n...\n\nSideboard\n2 Spell Pierce"}
              />
              <div className="export-row" style={{ marginTop: 12 }}>
                <button type="button" className="button secondary" onClick={importManualDeck} disabled={loading}>
                  Import Deck
                </button>
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => {
                    setManualMainboard([]);
                    setManualSideboard([]);
                    setManualCommander("");
                    setManualImportText("");
                    setAnalysis(null);
                    window.localStorage.removeItem(MANUAL_DRAFT_STORAGE_KEY);
                  }}
                >
                  Clear Draft
                </button>
              </div>
            </div>

            <div className="panel form-card">
              <div className="label">Mainboard ({mainboardCount})</div>
              <ul className="card-list">
                {manualMainboard.map((card) => renderEditableManualCard(card, "mainboard"))}
                {!manualMainboard.length ? <li className="card-row"><span className="muted">Add cards to begin building.</span></li> : null}
              </ul>
            </div>

            {format !== "commander" ? (
              <div className="panel form-card">
                <div className="label">Sideboard ({sideboardCount})</div>
                <ul className="card-list">
                  {manualSideboard.map((card) => renderEditableManualCard(card, "sideboard"))}
                  {!manualSideboard.length ? <li className="card-row"><span className="muted">Optional sideboard cards go here.</span></li> : null}
                </ul>
              </div>
            ) : null}

            <div className="panel form-card">
              <label className="label" htmlFor="manual-notes">Notes</label>
              <textarea id="manual-notes" className="textarea" value={manualNotes} onChange={(event) => setManualNotes(event.target.value)} />
            </div>

            <button type="button" className="button" onClick={analyzeManualDeck} disabled={loading}>
              {loading ? "Analyzing deck..." : "Analyze My Deck"}
            </button>
          </>
        )}
      </section>

      <section className="results-grid">
        <div className="panel results-card panel-strong">
          <div className="eyebrow">Deck Workshop</div>
          <h2 style={{ marginTop: 8, fontSize: 32 }}>
            {builderMode === "generate"
              ? (deck?.title ?? "Competitive deck output appears here")
              : (analysis?.inferred_archetype ?? "Manual deck analysis appears here")}
          </h2>
          <p className="muted">
            {builderMode === "generate"
              ? (deck?.strategy_summary ?? "Choose a format, set your constraints, and generate a tuned deck with transparent reasoning, readable card images, and clearer mana-base warnings.")
              : (analysis?.game_plan_summary ?? "Assemble a deck manually, then get a read on how it will play, what shell it resembles, and how to improve it.")}
          </p>
          {dataStatus ? (
            <p className="muted" style={{ marginTop: 12 }}>
              Card data: {dataStatus.card_source} ({dataStatus.card_count.toLocaleString()} cards)
              {" • "}
              Archetypes: {dataStatus.archetype_source} ({dataStatus.archetype_count})
            </p>
          ) : null}
          {error ? <p style={{ color: "#fca5a5" }}>{error}</p> : null}
          {builderMode === "generate" && deck ? (
              <div className="stats stats-four" style={{ marginTop: 18 }}>
              <div className="stat">
                <span className="muted">Overall</span>
                <strong>{deck.score.total}</strong>
              </div>
              <div className="stat">
                <span className="muted">Mana</span>
                <strong>{deck.score.mana}</strong>
              </div>
              <div className="stat">
                <span className="muted">Synergy</span>
                <strong>{deck.score.synergy}</strong>
              </div>
              <div className="stat">
                <span className="muted">Curve</span>
                <strong>{deck.score.curve}</strong>
              </div>
              <div className="stat">
                <span className="muted">Est. Price</span>
                <strong>{deck.estimated_price_usd ? `$${deck.estimated_price_usd.toFixed(0)}` : "-"}</strong>
              </div>
            </div>
          ) : null}
          {builderMode === "analyze" && analysis ? (
            <div className="stats stats-four" style={{ marginTop: 18 }}>
              <div className="stat">
                <span className="muted">Overall</span>
                <strong>{analysis.validation.score.total}</strong>
              </div>
              <div className="stat">
                <span className="muted">Health</span>
                <strong style={{ fontSize: 16 }}>{analysis.deck_health}</strong>
                {analysis.deck_health_explanation ? (
                  <p style={{ margin: "4px 0 0", fontSize: "0.8rem", color: "#6b7280", fontWeight: "normal" }}>
                    {analysis.deck_health_explanation}
                  </p>
                ) : null}
              </div>
              <div className="stat">
                <span className="muted">Mana</span>
                <strong>{analysis.validation.score.mana}</strong>
              </div>
              <div className="stat">
                <span className="muted">Curve</span>
                <strong>{analysis.validation.score.curve}</strong>
              </div>
            </div>
          ) : null}
          {builderMode === "generate" && deck ? (
            <div className="validation-banner" style={{ marginTop: 16 }}>
              <span className={`status-pill ${deck.is_legal ? "good" : "bad"}`}>
                {deck.is_legal ? "Legal" : "Needs fixes"}
              </span>
              <span className="muted">
                {deck.validation_errors.length
                  ? `${deck.validation_errors.length} blocking issue${deck.validation_errors.length === 1 ? "" : "s"}`
                  : deck.warnings.length
                    ? `${deck.warnings.length} warning${deck.warnings.length === 1 ? "" : "s"}`
                    : "No validation issues"}
              </span>
            </div>
          ) : null}
          {builderMode === "analyze" && analysis ? (
            <div className="validation-banner" style={{ marginTop: 16 }}>
              <span className={`status-pill ${analysis.validation.is_legal ? "good" : "bad"}`}>
                {analysis.validation.is_legal ? "Legal" : "Needs fixes"}
              </span>
              <span className="muted">
                {analysis.validation.errors.length
                  ? `${analysis.validation.errors.length} blocking issue${analysis.validation.errors.length === 1 ? "" : "s"}`
                  : analysis.validation.warnings.length
                    ? `${analysis.validation.warnings.length} warning${analysis.validation.warnings.length === 1 ? "" : "s"}`
                    : "No validation issues"}
              </span>
            </div>
          ) : null}
        </div>

        {builderMode === "generate" && deck ? (
          <>
            <div className="panel results-card">
              <div className="deck-columns">
                <div>
                  <div className="label">Mainboard</div>
                  <ul className="card-list">
                    {deck.mainboard.map((card) => renderDeckCard(card, "main", `${card.quantity}x`))}
                  </ul>
                </div>
                <div>
                  <div className="label">
                    {deck.commander ? "Commander / Sideboard" : "Sideboard"}
                    {deck.commander ? (
                      <span className="chip" style={{ marginLeft: 8, fontSize: "0.72rem", opacity: 0.75 }}>
                        {selectedCommanderName && selectedCommanderName === deck.commander ? "Your pick" : "Recommended"}
                      </span>
                    ) : null}
                  </div>
                  <ul className="card-list">
                    {deck.commander ? renderDeckCard({ name: deck.commander, quantity: 1 }, "commander", "Commander") : null}
                    {(deck.sideboard.length ? deck.sideboard : deck.card_notes.slice(0, 6).map((note) => ({ name: note.name, quantity: 1 }))).map((card) =>
                      renderDeckCard(card, "sideboard", deck.sideboard.length ? `${card.quantity}x` : "note")
                    )}
                  </ul>
                </div>
              </div>
            </div>

            <div className="panel results-card">
              <div className="label">Why This Deck</div>
              <ul className="card-list">
                {deck.explanation.map((item, index) => (
                  <li key={index} className="card-row">
                    <span>{item}</span>
                  </li>
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

            {format === "commander" && selectedCommanderProfile ? (
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
                <div className="label">Validation Warnings</div>
                <ul className="card-list">
                  {deck.warnings.map((item, index) => (
                    <li key={`warning-${index}`} className="card-row">
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {deck.validation_errors.length ? (
              <div className="panel results-card">
                <div className="label">Validation Errors</div>
                <ul className="card-list">
                  {deck.validation_errors.map((item, index) => (
                    <li key={`error-${index}`} className="card-row">
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {deck.selected_archetype ? (
              <>
                <div className="panel results-card panel-strong">
                  <div className="label">Selected Archetype</div>
                  <h3 style={{ marginTop: 0, marginBottom: 8 }}>{deck.selected_archetype.name}</h3>
                  <p className="muted" style={{ marginTop: 0 }}>
                    {deck.selected_archetype.strategy}
                  </p>
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

                {renderPackageList("Core Cards", deck.selected_archetype.metadata.core_cards)}
                {renderPackageList("Flex Slots", deck.selected_archetype.metadata.flex_cards)}
                {renderPackageList("Land Packages", deck.selected_archetype.metadata.land_packages)}
                {renderPackageList("Common Sideboard Packages", deck.selected_archetype.metadata.sideboard_packages)}
                {deck.selected_archetype.metadata.commander_package ? renderPackageList("Commander Signature Cards", deck.selected_archetype.metadata.commander_package.signature_cards) : null}
                {deck.selected_archetype.metadata.commander_package ? renderPackageList("Commander Support Packages", deck.selected_archetype.metadata.commander_package.synergy_packages) : null}
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

            <div className="panel results-card">
              <label className="label" htmlFor="refine">Refine Deck</label>
              <textarea id="refine" className="textarea" value={refinePrompt} onChange={(event) => setRefinePrompt(event.target.value)} />
              <button type="button" className="button secondary" onClick={refineDeck} disabled={loading} style={{ marginTop: 12 }}>
                Apply Refinement
              </button>
            </div>

            <div className="panel results-card">
              <div className="label">Export Deck</div>
              <div className="export-row">
                <select className="select" value={exportTarget} onChange={(event) => setExportTarget(event.target.value as ExportTarget)}>
                  <option value="plain">Plain Text</option>
                  <option value="arena">MTG Arena</option>
                  <option value="csv">CSV</option>
                  <option value="moxfield">Moxfield</option>
                </select>
                <button type="button" className="button secondary" onClick={exportDeck} disabled={exportLoading}>
                  {exportLoading ? "Exporting..." : "Build Export"}
                </button>
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
        ) : null}

        {builderMode === "analyze" && analysis ? (
          <>
            <div className="panel results-card">
              <div className="label">What This Deck Is Doing</div>
              <p>{analysis.game_plan_summary}</p>
              <p className="muted" style={{ marginTop: 12 }}>{analysis.play_pattern_summary}</p>
            </div>

            {analysis.ai_coaching_note ? (
              <div className="panel results-card panel-strong">
                <div className="label">Claude&apos;s Top Coaching Tips</div>
                <div style={{ whiteSpace: "pre-line", lineHeight: 1.7 }}>{analysis.ai_coaching_note}</div>
              </div>
            ) : null}

            <div className="panel results-card">
              <div className="label">Style / Archetype</div>
              <ul className="card-list">
                <li className="card-row">
                  <span>Style</span>
                  <span className="muted">{analysis.inferred_style}</span>
                </li>
                <li className="card-row">
                  <span>Closest Shell</span>
                  <span className="muted">{analysis.inferred_archetype}</span>
                </li>
                <li className="card-row" style={{ display: "block" }}>
                  <span>{analysis.similarity_label}</span>
                </li>
              </ul>
              {analysis.nearest_archetypes.length ? (
                <p className="muted" style={{ marginTop: 12 }}>
                  Nearby archetypes: {analysis.nearest_archetypes.join(", ")}
                </p>
              ) : null}
            </div>

            <div className="panel results-card">
              <div className="deck-columns">
                <div>
                  <div className="label">Mainboard</div>
                  <ul className="card-list">
                    {manualMainboard.map((card) => renderDeckCard(card, "manual-main", `${card.quantity}x`))}
                  </ul>
                </div>
                <div>
                  <div className="label">{format === "commander" ? "Commander / Sideboard" : "Sideboard"}</div>
                  <ul className="card-list">
                    {format === "commander" && manualCommander ? renderDeckCard({ name: manualCommander, quantity: 1 }, "manual-commander", "Commander") : null}
                    {manualSideboard.map((card) => renderDeckCard(card, "manual-side", `${card.quantity}x`))}
                    {!manualSideboard.length && format !== "commander" ? <li className="card-row"><span className="muted">No sideboard cards submitted.</span></li> : null}
                  </ul>
                </div>
              </div>
            </div>

            <div className="panel results-card">
              <div className="label">Strengths</div>
              <ul className="card-list">
                {analysis.strengths.map((item, index) => (
                  <li key={`strength-${index}`} className="card-row"><span>{item}</span></li>
                ))}
              </ul>
            </div>

            <div className="panel results-card">
              <div className="label">Weaknesses</div>
              <ul className="card-list">
                {analysis.weaknesses.map((item, index) => (
                  <li key={`weakness-${index}`} className="card-row"><span>{item}</span></li>
                ))}
              </ul>
            </div>

            <div className="panel results-card">
              <div className="label">Suggested Improvements</div>
              <div className="card-list">
                {analysis.advice.keep_doing.length ? <div className="card-row" style={{ display: "block" }}><strong>Keep Doing</strong><p className="muted">{analysis.advice.keep_doing.join(" ")}</p></div> : null}
                {analysis.advice.watch_out_for.length ? <div className="card-row" style={{ display: "block" }}><strong>Watch Out For</strong><p className="muted">{analysis.advice.watch_out_for.join(" ")}</p></div> : null}
                {analysis.advice.add_more_of.length ? <div className="card-row" style={{ display: "block" }}><strong>Add More Of</strong><p className="muted">{analysis.advice.add_more_of.join(" ")}</p></div> : null}
                {analysis.advice.cut_some_of.length ? <div className="card-row" style={{ display: "block" }}><strong>Cut Some Of</strong><p className="muted">{analysis.advice.cut_some_of.join(" ")}</p></div> : null}
                {analysis.advice.possible_upgrades.length ? <div className="card-row" style={{ display: "block" }}><strong>Possible Upgrades</strong><p className="muted">{analysis.advice.possible_upgrades.join(" ")}</p></div> : null}
              </div>
            </div>

            {analysis.improvement_suggestions.length ? (
              <div className="panel results-card">
                <div className="label">Upgrade Packages</div>
                <ul className="card-list">
                  {analysis.improvement_suggestions.map((item) => (
                    <li key={item.category} className="card-row" style={{ display: "block" }}>
                      <strong>{item.category}</strong>
                      <p className="muted" style={{ marginTop: 6 }}>{item.summary}</p>
                      {item.candidate_cards.length ? (
                        <div className="chips" style={{ marginTop: 8 }}>
                          {item.candidate_cards.map((cardName) => (
                            <button key={`${item.category}-${cardName}`} type="button" className="chip" onClick={() => void openCard(cardName)}>
                              {cardName}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {analysis.swap_recommendations.length ? (
              <div className="panel results-card panel-strong">
                <div className="label">Exact Add / Cut Ideas</div>
                <ul className="card-list">
                  {analysis.swap_recommendations.map((item, index) => (
                    <li key={`${item.category}-${item.cut_card}-${item.add_card}-${index}`} className="card-row" style={{ display: "block" }}>
                      <strong>{item.category}</strong>
                      <div className="chips" style={{ marginTop: 8 }}>
                        <button type="button" className="chip" onClick={() => void openCard(item.cut_card)}>
                          Cut {item.cut_card}
                        </button>
                        <button type="button" className="chip" onClick={() => void openCard(item.add_card)}>
                          Add {item.add_card}
                        </button>
                      </div>
                      <p className="muted" style={{ marginTop: 8 }}>{item.reason}</p>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {analysis.nearest_shell_comparison ? (
              <div className="panel results-card">
                <div className="label">Nearest Shell Comparison</div>
                <p className="muted">
                  {analysis.nearest_shell_comparison.shell_name} • confidence {Math.round(analysis.nearest_shell_comparison.confidence * 100)}%
                </p>
                <div className="deck-columns">
                  <div>
                    <div className="label">Shared Cards</div>
                    <ul className="card-list">
                      {analysis.nearest_shell_comparison.overlap_cards.map((cardName) => (
                        <li key={`overlap-${cardName}`} className="card-row">
                          <button type="button" className="card-button" onClick={() => void openCard(cardName)}>{cardName}</button>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <div className="label">Missing From Shell</div>
                    <ul className="card-list">
                      {analysis.nearest_shell_comparison.missing_cards.map((cardName) => (
                        <li key={`missing-${cardName}`} className="card-row">
                          <button type="button" className="card-button" onClick={() => void openCard(cardName)}>{cardName}</button>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
                {analysis.nearest_shell_comparison.off_plan_cards.length ? (
                  <>
                    <div className="label" style={{ marginTop: 16 }}>Possible Off-Plan Cards</div>
                    <div className="chips" style={{ marginTop: 8 }}>
                      {analysis.nearest_shell_comparison.off_plan_cards.map((cardName) => (
                        <button key={`offplan-${cardName}`} type="button" className="chip" onClick={() => void openCard(cardName)}>
                          {cardName}
                        </button>
                      ))}
                    </div>
                  </>
                ) : null}
              </div>
            ) : null}

            {(analysis.role_summary.length || analysis.mana_curve.length) ? (
              <div className="panel results-card">
                <div className="label">Validation / Mana / Roles</div>
                <div className="deck-columns">
                  <div>
                    <div className="label">Roles</div>
                    <ul className="card-list">
                      {analysis.role_summary.map((item) => (
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
                      {analysis.mana_curve.map((point) => (
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

            {analysis.synergy_observations.length ? (
              <div className="panel results-card">
                <div className="label">Synergy Notes</div>
                <ul className="card-list">
                  {analysis.synergy_observations.map((item, index) => (
                    <li key={`synergy-${index}`} className="card-row"><span>{item}</span></li>
                  ))}
                </ul>
              </div>
            ) : null}

            {analysis.validation.errors.length ? (
              <div className="panel results-card">
                <div className="label">Validation Errors</div>
                <ul className="card-list">
                  {analysis.validation.errors.map((item, index) => (
                    <li key={`analysis-error-${index}`} className="card-row"><span>{item}</span></li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        ) : null}
      </section>

      {selectedCard ? (
        <div className="card-modal-backdrop" role="presentation" onClick={() => setSelectedCard(null)}>
          <div className="card-modal panel panel-strong" role="dialog" aria-modal="true" aria-labelledby="card-detail-name" aria-describedby="card-detail-oracle" onClick={(event) => event.stopPropagation()}>
            <div className="card-modal-header">
              <div>
                <div className="label">Card Detail</div>
                <h3 id="card-detail-name" style={{ marginTop: 0, marginBottom: 6 }}>{selectedCard.name}</h3>
                <p className="muted" style={{ margin: 0 }}>{selectedCard.type_line || "Card details"}</p>
              </div>
              <button type="button" className="chip" onClick={() => setSelectedCard(null)}>Close</button>
            </div>
            <div className="card-modal-grid">
              <div className="card-image-shell">
                {cardLoading ? (
                  <div style={{ width: 265, height: 370, background: "#e5e7eb", borderRadius: 8 }} aria-label="Loading card image" />
                ) : null}
                {!cardLoading && selectedCard.image_uri ? <img src={selectedCard.image_uri} alt={selectedCard.name} className="card-image" /> : null}
                {!cardLoading && !selectedCard.image_uri && selectedCard.faces[0]?.image_uri ? <img src={selectedCard.faces[0].image_uri} alt={selectedCard.name} className="card-image" /> : null}
                {!cardLoading && !selectedCard.image_uri && !selectedCard.faces[0]?.image_uri ? <p className="muted">No image available for this card.</p> : null}
              </div>
              <div className="card-copy">
                <p><strong>Mana Cost:</strong> {selectedCard.mana_cost || "-"}</p>
                {selectedCard.rarity ? <p><strong>Rarity:</strong> {selectedCard.rarity}</p> : null}
                <p><strong>Oracle Text:</strong></p>
                <pre id="card-detail-oracle" className="oracle-text">{selectedCard.oracle_text || "No rules text available."}</pre>
                {selectedCard.faces.length ? (
                  <div>
                    <p><strong>Faces:</strong></p>
                    <ul className="card-list">
                      {selectedCard.faces.map((face, index) => (
                        <li key={`${face.name ?? "face"}-${index}`} className="card-row" style={{ display: "block" }}>
                          <strong>{face.name ?? `Face ${index + 1}`}</strong>
                          <div className="muted">{face.type_line}</div>
                          <pre className="oracle-text">{face.oracle_text || "No face text available."}</pre>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {selectedCard.price_usd ? <p><strong>Cached Price:</strong> ${selectedCard.price_usd.toFixed(2)}</p> : null}
                {selectedCard.tags.length ? <p><strong>Tags:</strong> {selectedCard.tags.join(", ")}</p> : null}
                <div className="export-row" style={{ marginTop: 12 }}>
                  {selectedCard.purchase_links?.scryfall ? (
                    <a className="button secondary" href={selectedCard.purchase_links.scryfall} target="_blank" rel="noreferrer">
                      Open Scryfall
                    </a>
                  ) : null}
                  {selectedCard.purchase_links?.amazon_search ? (
                    <a className="button secondary" href={selectedCard.purchase_links.amazon_search} target="_blank" rel="noreferrer">
                      Search Amazon
                    </a>
                  ) : null}
                </div>
                {cardError ? <p style={{ color: "#fca5a5" }}>{cardError}</p> : null}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
