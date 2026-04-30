"use client";

import { useEffect, useMemo, useState } from "react";

import { AnalysisResults } from "./workshop/analysis-results";
import { AnalyzeForm, type ManualZone } from "./workshop/analyze-form";
import { CardDetailModal } from "./workshop/card-detail-modal";
import { CommanderPicker, type CommanderMode } from "./workshop/commander-picker";
import { DeckRationaleView } from "./workshop/deck-rationale";
import { DeckResults } from "./workshop/deck-results";
import { FormatColorPicker } from "./workshop/format-color-picker";
import { GenerateForm } from "./workshop/generate-form";
import { StrategyPicker } from "./workshop/strategy-picker";
import { useCardDetail } from "@/hooks/use-card-detail";
import { useDataStatus } from "@/hooks/use-data-status";
import { useDeckAnalyzer } from "@/hooks/use-deck-analyzer";
import { useDeckGenerator } from "@/hooks/use-deck-generator";
import { useDeckRationale } from "@/hooks/use-deck-rationale";
import type { ExportTarget } from "@/lib/api";
import { clearManualDraft, loadManualDraft, saveManualDraft } from "@/lib/manual-draft";
import { activeTags, parseBudgetInput, type StrategyId } from "@/lib/strategies";
import type { CardRef, CommanderProfile, FormatName } from "@/lib/types";
import type { CommanderSort } from "@/hooks/use-commander-search";

type BuilderMode = "generate" | "analyze";

export function DeckWorkshop() {
  const [builderMode, setBuilderMode] = useState<BuilderMode>("generate");
  const [format, setFormat] = useState<FormatName>("modern");
  const [colors, setColors] = useState<string[]>(["U", "R"]);
  const [selectedStrategies, setSelectedStrategies] = useState<StrategyId[]>(["aggro", "spellslinger"]);
  const [budget, setBudget] = useState("400");
  const [prompt, setPrompt] = useState("Build me a strong Modern prowess deck that feels explosive and is still friendly to a newer player.");
  const [refinePrompt, setRefinePrompt] = useState("Make it a bit cheaper without losing too much pressure.");
  const [exportContent, setExportContent] = useState("");
  const [expertMode, setExpertMode] = useState(false);
  const [commanderMode, setCommanderMode] = useState<CommanderMode>("recommend");
  const [commanderSort, setCommanderSort] = useState<CommanderSort>("match");
  const [commanderSearch, setCommanderSearch] = useState("");
  const [selectedCommanderName, setSelectedCommanderName] = useState("");
  const [selectedCommanderProfile, setSelectedCommanderProfile] = useState<CommanderProfile | null>(null);

  const [manualMainboard, setManualMainboard] = useState<CardRef[]>([]);
  const [manualSideboard, setManualSideboard] = useState<CardRef[]>([]);
  const [manualCommander, setManualCommander] = useState("");
  const [manualNotes, setManualNotes] = useState("Tell me how this deck plays, what shell it resembles, and what I should improve.");
  const [manualImportText, setManualImportText] = useState("");
  const [deepAnalysis, setDeepAnalysis] = useState(true);

  const dataStatus = useDataStatus();
  const cardDetail = useCardDetail();
  const generator = useDeckGenerator();
  const analyzer = useDeckAnalyzer();
  const rationale = useDeckRationale();

  const handleRequestRationale = async () => {
    if (format !== "modern") return;
    rationale.submit({
      format: "modern",
      colors,
      deck_size: 60,
      budget_usd: parseBudgetInput(budget) ?? undefined,
      include_cards: [],
      exclude_cards: [],
      archetype_recipes: [],
      rounds: 8,
      proposals_per_round: 3,
      sim_runs_per_eval: 100,
    });
  };

  const tags = useMemo(() => activeTags(selectedStrategies), [selectedStrategies]);
  const error = generator.error ?? analyzer.error;
  const loading = generator.loading || analyzer.loading;
  const deck = generator.deck;
  const analysis = analyzer.analysis;

  // Hydrate manual draft once on mount.
  useEffect(() => {
    const draft = loadManualDraft();
    if (!draft) return;
    if (draft.format) setFormat(draft.format);
    setManualMainboard(draft.mainboard ?? []);
    setManualSideboard(draft.sideboard ?? []);
    setManualCommander(draft.commander ?? "");
    setManualNotes(draft.notes ?? "Tell me how this deck plays, what shell it resembles, and what I should improve.");
    if (draft.refinePrompt) setRefinePrompt(draft.refinePrompt);
  }, []);

  // Persist manual draft.
  useEffect(() => {
    saveManualDraft({
      format,
      mainboard: manualMainboard,
      sideboard: manualSideboard,
      commander: manualCommander,
      notes: manualNotes,
      refinePrompt
    });
  }, [format, manualMainboard, manualSideboard, manualCommander, manualNotes, refinePrompt]);

  // Reset commander state when leaving commander format.
  useEffect(() => {
    if (format !== "commander") {
      setSelectedCommanderProfile(null);
      setSelectedCommanderName("");
    }
  }, [format]);

  // Sync color picker with the selected commander's identity.
  useEffect(() => {
    if (selectedCommanderProfile?.colors.length) {
      setColors(selectedCommanderProfile.colors);
    }
  }, [selectedCommanderProfile]);

  function handleManualUpdate(zone: ManualZone, updater: (cards: CardRef[]) => CardRef[]) {
    if (zone === "mainboard") setManualMainboard((current) => updater(current));
    else setManualSideboard((current) => updater(current));
  }

  function addManualCard(name: string, zone: ManualZone) {
    handleManualUpdate(zone, (cards) => {
      const existing = cards.find((item) => item.name === name);
      if (existing) return cards.map((item) => (item.name === name ? { ...item, quantity: item.quantity + 1 } : item));
      return [...cards, { name, quantity: 1 }];
    });
  }

  function setManualQuantity(name: string, zone: ManualZone, quantity: number) {
    handleManualUpdate(zone, (cards) => {
      if (quantity <= 0) return cards.filter((item) => item.name !== name);
      return cards.map((item) => (item.name === name ? { ...item, quantity } : item));
    });
  }

  function moveManualCard(name: string, from: ManualZone) {
    const fromCards = from === "mainboard" ? manualMainboard : manualSideboard;
    const card = fromCards.find((item) => item.name === name);
    if (!card) return;
    setManualQuantity(name, from, 0);
    addManualCard(name, from === "mainboard" ? "sideboard" : "mainboard");
  }

  async function handleGenerate() {
    const parsedBudget = parseBudgetInput(budget);
    if (budget.trim() && parsedBudget === undefined) {
      generator.setError("Budget must be a non-negative number.");
      return;
    }
    if (format === "commander" && commanderMode === "selected" && !selectedCommanderName) {
      generator.setError("Select a commander before building a commander deck from an explicit commander.");
      return;
    }
    setExportContent("");
    analyzer.reset();
    await generator.generate({
      format,
      colors,
      commander_name: format === "commander" && commanderMode === "selected" ? selectedCommanderName || undefined : undefined,
      playstyle_tags: tags.playstyle,
      theme_tags: tags.theme,
      budget: parsedBudget,
      prompt
    });
  }

  async function handleAnalyze() {
    setExportContent("");
    generator.reset();
    await analyzer.analyze({
      format,
      commander: format === "commander" ? manualCommander || undefined : undefined,
      mainboard: manualMainboard,
      sideboard: format === "commander" ? [] : manualSideboard,
      notes: manualNotes,
      deep_analysis: deepAnalysis
    });
  }

  async function handleImport() {
    const parsed = await analyzer.importText(format, manualImportText);
    if (!parsed) return;
    setManualMainboard(parsed.mainboard);
    setManualSideboard(parsed.sideboard);
    setManualCommander(parsed.commander ?? "");
  }

  function handleClearDraft() {
    setManualMainboard([]);
    setManualSideboard([]);
    setManualCommander("");
    setManualImportText("");
    analyzer.reset();
    clearManualDraft();
  }

  async function handleRefine() {
    setExportContent("");
    await generator.refine(refinePrompt);
  }

  async function handleExport(target: ExportTarget) {
    const content = await generator.exportDeck(target);
    if (content !== null) setExportContent(content);
  }

  return (
    <div className="builder">
      <section className="form-grid" aria-label="Deck builder controls">
        <div className="panel form-card panel-strong">
          <span className="label">Mode</span>
          <div className="chips">
            <button type="button" className={`chip ${builderMode === "generate" ? "active" : ""}`} onClick={() => setBuilderMode("generate")} aria-pressed={builderMode === "generate"}>
              Generate
            </button>
            <button type="button" className={`chip ${builderMode === "analyze" ? "active" : ""}`} onClick={() => setBuilderMode("analyze")} aria-pressed={builderMode === "analyze"}>
              Analyze My Deck
            </button>
          </div>
        </div>

        <FormatColorPicker
          format={format}
          colors={colors}
          onFormatChange={setFormat}
          onColorsChange={setColors}
        />

        <CommanderPicker
          format={format}
          colors={colors}
          playstyleTags={tags.playstyle}
          themeTags={tags.theme}
          selectedCommanderName={selectedCommanderName}
          commanderMode={commanderMode}
          commanderSearch={commanderSearch}
          commanderSort={commanderSort}
          onModeChange={setCommanderMode}
          onSearchChange={setCommanderSearch}
          onSortChange={setCommanderSort}
          onSelect={setSelectedCommanderName}
          onOpenCard={(name) => void cardDetail.open(name)}
          onProfileChange={setSelectedCommanderProfile}
        />

        <StrategyPicker selected={selectedStrategies} onChange={setSelectedStrategies} />

        {builderMode === "generate" ? (
          <GenerateForm
            expertMode={expertMode}
            onExpertModeChange={setExpertMode}
            budget={budget}
            onBudgetChange={setBudget}
            prompt={prompt}
            onPromptChange={setPrompt}
            onSubmit={() => void handleGenerate()}
            loading={loading}
          />
        ) : (
          <AnalyzeForm
            format={format}
            manualMainboard={manualMainboard}
            manualSideboard={manualSideboard}
            manualCommander={manualCommander}
            manualNotes={manualNotes}
            importText={manualImportText}
            loading={loading}
            deepAnalysis={deepAnalysis}
            onDeepAnalysisChange={setDeepAnalysis}
            onCommanderChange={setManualCommander}
            onNotesChange={setManualNotes}
            onImportTextChange={setManualImportText}
            onAddCard={addManualCard}
            onChangeQuantity={setManualQuantity}
            onMoveCard={moveManualCard}
            onImport={() => void handleImport()}
            onClearDraft={handleClearDraft}
            onAnalyze={() => void handleAnalyze()}
            onOpenCard={(name) => void cardDetail.open(name)}
          />
        )}
      </section>

      <section className="results-grid" aria-label="Deck output">
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
          {error ? <p style={{ color: "#fca5a5" }} role="alert">{error}</p> : null}

          {builderMode === "generate" && deck ? <ResultStats label="Quality" score={deck.score} extra={{ price: deck.estimated_price_usd }} /> : null}
          {builderMode === "analyze" && analysis ? (
            <ResultStats
              label="Quality"
              score={analysis.validation.score}
              health={{ value: analysis.deck_health, explanation: analysis.deck_health_explanation }}
            />
          ) : null}

          {builderMode === "generate" && deck ? (
            <LegalityBanner isLegal={deck.is_legal} errorCount={deck.validation_errors.length} warningCount={deck.warnings.length} />
          ) : null}
          {builderMode === "analyze" && analysis ? (
            <LegalityBanner isLegal={analysis.validation.is_legal} errorCount={analysis.validation.errors.length} warningCount={analysis.validation.warnings.length} />
          ) : null}
        </div>

        {builderMode === "generate" && deck ? (
          <>
            <DeckResults
              deck={deck}
              meta={generator.meta}
              selectedCommanderName={selectedCommanderName}
              selectedCommanderProfile={selectedCommanderProfile}
              refinePrompt={refinePrompt}
              onRefinePromptChange={setRefinePrompt}
              onRefine={() => void handleRefine()}
              onExport={(target) => void handleExport(target)}
              exportContent={exportContent}
              onOpenCard={(name) => void cardDetail.open(name)}
              loading={loading}
            />
            {format === "modern" ? (
              <RationalePanel
                rationale={rationale.rationale}
                status={rationale.status}
                error={rationale.error}
                onRequest={() => void handleRequestRationale()}
                onReset={rationale.reset}
              />
            ) : null}
          </>
        ) : null}

        {builderMode === "analyze" && analysis ? (
          <AnalysisResults
            analysis={analysis}
            format={format}
            manualMainboard={manualMainboard}
            manualSideboard={manualSideboard}
            manualCommander={manualCommander}
            onOpenCard={(name) => void cardDetail.open(name)}
          />
        ) : null}
      </section>

      {cardDetail.card ? (
        <CardDetailModal
          card={cardDetail.card}
          loading={cardDetail.loading}
          error={cardDetail.error}
          onClose={cardDetail.close}
        />
      ) : null}
    </div>
  );
}

function ResultStats({
  label,
  score,
  extra,
  health
}: {
  label: string;
  score: { total: number; mana: number; synergy: number; curve: number };
  extra?: { price?: number | null };
  health?: { value: string; explanation: string };
}) {
  return (
    <div className="stats stats-four" style={{ marginTop: 18 }}>
      <div className="stat">
        <span className="muted">Overall {label}</span>
        <strong>{score.total}</strong>
      </div>
      {health ? (
        <div className="stat">
          <span className="muted">Health</span>
          <strong style={{ fontSize: 16 }}>{health.value}</strong>
          {health.explanation ? <p style={{ margin: "4px 0 0", fontSize: "0.8rem", color: "#9ca3af" }}>{health.explanation}</p> : null}
        </div>
      ) : (
        <div className="stat">
          <span className="muted">Mana</span>
          <strong>{score.mana}</strong>
        </div>
      )}
      <div className="stat">
        <span className="muted">Synergy</span>
        <strong>{score.synergy}</strong>
      </div>
      <div className="stat">
        <span className="muted">{extra?.price !== undefined ? "Est. Price" : "Curve"}</span>
        <strong>{extra?.price !== undefined && extra?.price !== null ? `$${extra.price.toFixed(0)}` : score.curve}</strong>
      </div>
    </div>
  );
}

function LegalityBanner({ isLegal, errorCount, warningCount }: { isLegal: boolean; errorCount: number; warningCount: number }) {
  return (
    <div className="validation-banner" style={{ marginTop: 16 }}>
      <span className={`status-pill ${isLegal ? "good" : "bad"}`}>{isLegal ? "Legal" : "Needs fixes"}</span>
      {errorCount ? (
        <span className="status-pill bad">{errorCount} blocking issue{errorCount === 1 ? "" : "s"}</span>
      ) : warningCount ? (
        <span className="muted">{warningCount} quality warning{warningCount === 1 ? "" : "s"}</span>
      ) : (
        <span className="muted">No validation issues</span>
      )}
    </div>
  );
}

function RationalePanel({
  rationale,
  status,
  error,
  onRequest,
  onReset,
}: {
  rationale: import("@/lib/types").DeckRationaleData | null;
  status: "idle" | "submitting" | "polling" | "succeeded" | "failed";
  error: string | null;
  onRequest: () => void;
  onReset: () => void;
}) {
  if (status === "idle") {
    return (
      <div className="mt-4 rounded-lg border border-zinc-700 bg-zinc-900/40 p-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="text-sm font-semibold text-zinc-100">Tournament-grade rationale</div>
            <div className="text-xs text-zinc-400">
              Run the simulator-driven optimizer to produce a structured win-plan, mulligan guide, matchup matrix, and critic transcript. ~30s.
            </div>
          </div>
          <button
            type="button"
            onClick={onRequest}
            className="rounded bg-amber-500 px-3 py-1.5 text-sm font-medium text-zinc-900 hover:bg-amber-400"
          >
            Run optimizer
          </button>
        </div>
      </div>
    );
  }

  if (status === "submitting" || status === "polling") {
    return (
      <div className="mt-4 rounded-lg border border-zinc-700 bg-zinc-900/40 p-4 text-sm text-zinc-300">
        {status === "submitting" ? "Submitting optimizer job…" : "Optimizer running… (polling for results)"}
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div className="mt-4 rounded-lg border border-rose-700 bg-rose-950/40 p-4 text-sm text-rose-200">
        Optimizer failed: {error ?? "unknown error"}
        <button
          type="button"
          onClick={onReset}
          className="ml-3 underline text-rose-100"
        >
          dismiss
        </button>
      </div>
    );
  }

  if (rationale) {
    return (
      <div className="mt-4">
        <DeckRationaleView rationale={rationale} />
      </div>
    );
  }

  return null;
}
