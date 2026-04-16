"use client";

import { useEffect, useState } from "react";

import type {
  ArchetypePackage,
  CardDetailResponse,
  CardRecord,
  CardRef,
  DeckResponse,
  FormatName,
  MetaSummaryResponse
} from "@/lib/types";

const COLORS = ["W", "U", "B", "R", "G"];
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

type ScryfallCard = {
  image_uris?: {
    normal?: string;
    large?: string;
  };
  oracle_text?: string;
  card_faces?: Array<{
    image_uris?: {
      normal?: string;
      large?: string;
    };
    oracle_text?: string;
  }>;
};

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

function mergeCardData(localCard: CardRecord | null, scryfallCard: ScryfallCard | null, name: string): CardRecord {
  const faceImage = scryfallCard?.card_faces?.find((face) => face.image_uris?.large || face.image_uris?.normal)?.image_uris;
  const imageUri = localCard?.image_uri ?? scryfallCard?.image_uris?.large ?? scryfallCard?.image_uris?.normal ?? faceImage?.large ?? faceImage?.normal ?? null;
  const faceOracleText = scryfallCard?.card_faces?.map((face) => face.oracle_text).filter(Boolean).join("\n\n");

  return {
    oracle_id: localCard?.oracle_id ?? null,
    name,
    mana_cost: localCard?.mana_cost ?? "",
    mana_value: localCard?.mana_value ?? 0,
    colors: localCard?.colors ?? [],
    color_identity: localCard?.color_identity ?? [],
    type_line: localCard?.type_line ?? "",
    oracle_text: localCard?.oracle_text || scryfallCard?.oracle_text || faceOracleText || "",
    set_code: localCard?.set_code ?? null,
    released_at: localCard?.released_at ?? null,
    image_uri: imageUri,
    price_usd: localCard?.price_usd ?? null,
    legalities: localCard?.legalities ?? {},
    tags: localCard?.tags ?? []
  };
}

export function DeckWorkshop() {
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

  const toggleValue = (value: string, values: string[], setValues: (next: string[]) => void) => {
    if (values.includes(value)) {
      setValues(values.filter((item) => item !== value));
      return;
    }
    setValues([...values, value]);
  };

  async function openCard(name: string) {
    setCardLoading(true);
    setCardError(null);

    try {
      let localCard: CardRecord | null = null;
      const localResponse = await fetch(`${API_BASE}/v1/cards/${encodeURIComponent(name)}`);
      if (localResponse.ok) {
        const payload = (await localResponse.json()) as CardDetailResponse;
        localCard = payload.card;
      }

      let scryfallCard: ScryfallCard | null = null;
      try {
        const scryfallResponse = await fetch(`https://api.scryfall.com/cards/named?exact=${encodeURIComponent(name)}`);
        if (scryfallResponse.ok) {
          scryfallCard = (await scryfallResponse.json()) as ScryfallCard;
        }
      } catch {
        // Fall back to the local payload if the remote image lookup fails.
      }

      const mergedCard = mergeCardData(localCard, scryfallCard, name);
      if (!mergedCard.image_uri) {
        setCardError("No card image was available for this card.");
      }
      setSelectedCard(mergedCard);
    } catch (fetchError) {
      setCardError(fetchError instanceof Error ? fetchError.message : "Could not load card details.");
      setSelectedCard({
        oracle_id: null,
        name,
        mana_cost: "",
        mana_value: 0,
        colors: [],
        color_identity: [],
        type_line: "",
        oracle_text: "",
        set_code: null,
        released_at: null,
        image_uri: null,
        price_usd: null,
        legalities: {},
        tags: []
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
        body: JSON.stringify({
          format,
          colors,
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
      const metaResponse = await fetch(`${API_BASE}/v1/meta/summary?format=${format}`);
      if (metaResponse.ok) {
        const metaPayload = (await metaResponse.json()) as MetaSummaryResponse;
        setMeta(metaPayload);
      }
    } catch (generationError) {
      setError(generationError instanceof Error ? generationError.message : "Unknown error");
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

  async function refineDeck() {
    if (!deck) return;
    setLoading(true);
    setError(null);
    setExportContent("");
    try {
      const response = await fetch(`${API_BASE}/v1/decks/refine`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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
      </section>

      <section className="results-grid">
        <div className="panel results-card panel-strong">
          <div className="eyebrow">Deck Workshop</div>
          <h2 style={{ marginTop: 8, fontSize: 32 }}>{deck?.title ?? "Competitive deck output appears here"}</h2>
          <p className="muted">{deck?.strategy_summary ?? "Choose a format, set your constraints, and generate a tuned deck with transparent reasoning, readable card images, and clearer mana-base warnings."}</p>
          {error ? <p style={{ color: "#fca5a5" }}>{error}</p> : null}
          {deck ? (
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
                <span className="muted">Est. Price</span>
                <strong>{deck.estimated_price_usd ? `$${deck.estimated_price_usd.toFixed(0)}` : "-"}</strong>
              </div>
            </div>
          ) : null}
          {deck ? (
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
        </div>

        {deck ? (
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
                  <div className="label">{deck.commander ? "Commander / Sideboard" : "Sideboard"}</div>
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
                {renderPackageList("Common Sideboard Packages", deck.selected_archetype.metadata.sideboard_packages)}
              </>
            ) : null}

            {meta?.archetypes?.length ? (
              <div className="panel results-card">
                <div className="label">Format Meta Snapshot</div>
                <ul className="card-list">
                  {meta.archetypes.slice(0, 5).map((archetype) => (
                    <li key={archetype.id} className="card-row">
                      <span>{archetype.name}</span>
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
      </section>

      {selectedCard ? (
        <div className="card-modal-backdrop" role="presentation" onClick={() => setSelectedCard(null)}>
          <div className="card-modal panel panel-strong" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="card-modal-header">
              <div>
                <div className="label">Card Detail</div>
                <h3 style={{ marginTop: 0, marginBottom: 6 }}>{selectedCard.name}</h3>
                <p className="muted" style={{ margin: 0 }}>{selectedCard.type_line || "Card details"}</p>
              </div>
              <button type="button" className="chip" onClick={() => setSelectedCard(null)}>Close</button>
            </div>
            <div className="card-modal-grid">
              <div className="card-image-shell">
                {cardLoading ? <p className="muted">Loading card image...</p> : null}
                {selectedCard.image_uri ? <img src={selectedCard.image_uri} alt={selectedCard.name} className="card-image" /> : null}
                {!selectedCard.image_uri && !cardLoading ? <p className="muted">No image available for this card.</p> : null}
              </div>
              <div className="card-copy">
                <p><strong>Mana Cost:</strong> {selectedCard.mana_cost || "-"}</p>
                <p><strong>Oracle Text:</strong></p>
                <pre className="oracle-text">{selectedCard.oracle_text || "No rules text available."}</pre>
                {selectedCard.price_usd ? <p><strong>Cached Price:</strong> ${selectedCard.price_usd.toFixed(2)}</p> : null}
                {selectedCard.tags.length ? <p><strong>Tags:</strong> {selectedCard.tags.join(", ")}</p> : null}
                {cardError ? <p style={{ color: "#fca5a5" }}>{cardError}</p> : null}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
