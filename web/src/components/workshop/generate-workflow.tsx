"use client";

import { useEffect, useMemo, useState } from "react";

import { CardDetailModal } from "./card-detail-modal";
import { CommanderPicker, type CommanderMode } from "./commander-picker";
import { DeckDiffView } from "./deck-diff-view";
import { DeckEvaluationPanel } from "./deck-evaluation-panel";
import { DeckResults } from "./deck-results";
import { FormatColorPicker } from "./format-color-picker";
import { GenerateForm } from "./generate-form";
import { RationalePanel } from "./rationale-panel";
import { StrategyPicker } from "./strategy-picker";
import { WorkflowSummary } from "./workflow-summary";
import { useCardDetail } from "@/hooks/use-card-detail";
import type { CommanderSort } from "@/hooks/use-commander-search";
import { useDataStatus } from "@/hooks/use-data-status";
import { useDeckEvaluation } from "@/hooks/use-deck-evaluation";
import { useDeckGenerator } from "@/hooks/use-deck-generator";
import { useDeckRationale } from "@/hooks/use-deck-rationale";
import { useExperienceMode } from "@/hooks/use-experience-mode";
import { diffDecks, type DeckDiffResult, type ExportTarget } from "@/lib/api";
import { activeTags, parseBudgetInput, type StrategyId } from "@/lib/strategies";
import type { CommanderProfile, FormatName } from "@/lib/types";

export function GenerateWorkflow() {
  const [format, setFormat] = useState<FormatName>("modern");
  const [colors, setColors] = useState<string[]>(["U", "R"]);
  const [selectedStrategies, setSelectedStrategies] = useState<StrategyId[]>(["aggro", "spellslinger"]);
  const [budget, setBudget] = useState("400");
  const [prompt, setPrompt] = useState("Build me a strong Modern prowess deck that feels explosive and is still friendly to a newer player.");
  const [refinePrompt, setRefinePrompt] = useState("Make it a bit cheaper without losing too much pressure.");
  const [exportContent, setExportContent] = useState("");
  const [deckDiff, setDeckDiff] = useState<DeckDiffResult | null>(null);
  const [commanderMode, setCommanderMode] = useState<CommanderMode>("recommend");
  const [commanderSort, setCommanderSort] = useState<CommanderSort>("match");
  const [commanderSearch, setCommanderSearch] = useState("");
  const [selectedCommanderName, setSelectedCommanderName] = useState("");
  const [selectedCommanderProfile, setSelectedCommanderProfile] = useState<CommanderProfile | null>(null);

  const experience = useExperienceMode();
  const expertMode = experience.detailed;
  const setExpertMode = (value: boolean) => experience.setMode(value ? "expert" : "beginner");
  const dataStatus = useDataStatus();
  const cardDetail = useCardDetail();
  const generator = useDeckGenerator();
  const rationale = useDeckRationale();
  const evaluation = useDeckEvaluation();
  const tags = useMemo(() => activeTags(selectedStrategies), [selectedStrategies]);
  const deck = generator.deck;

  useEffect(() => {
    if (format !== "commander") {
      setSelectedCommanderProfile(null);
      setSelectedCommanderName("");
    }
  }, [format]);

  useEffect(() => {
    if (selectedCommanderProfile) setColors(selectedCommanderProfile.colors);
  }, [selectedCommanderProfile]);

  // The budget field only renders in expert mode, so beginners must never be
  // capped by its hidden default ("Off = no spend limit").
  const effectiveBudget = expertMode ? budget : "";

  async function handleGenerate() {
    const parsedBudget = parseBudgetInput(effectiveBudget);
    if (effectiveBudget.trim() && parsedBudget === undefined) {
      generator.setError("Budget must be a non-negative number.");
      return;
    }
    if (format === "commander" && commanderMode === "selected" && !selectedCommanderName) {
      generator.setError("Select a commander before building from your pick.");
      return;
    }
    setExportContent("");
    setDeckDiff(null);
    evaluation.reset();
    await generator.generate({
      format,
      colors,
      commander_name: format === "commander" && commanderMode === "selected" ? selectedCommanderName : undefined,
      playstyle_tags: tags.playstyle,
      theme_tags: tags.theme,
      budget: parsedBudget,
      experience_level: expertMode ? "expert" : "beginner",
      prompt
    });
  }

  async function handleRefine() {
    setExportContent("");
    const before = deck?.mainboard ?? [];
    const updated = await generator.refine(refinePrompt);
    if (!updated || !before.length) return;
    try {
      setDeckDiff(await diffDecks(before, updated.mainboard));
    } catch {
      setDeckDiff(null);
    }
    evaluation.reset();
  }

  async function handleExport(target: ExportTarget) {
    const content = await generator.exportDeck(target);
    if (content !== null) setExportContent(content);
  }

  function handleRequestRationale() {
    if (format !== "modern") return;
    void rationale.submit({
      format: "modern",
      colors,
      deck_size: 60,
      budget_usd: parseBudgetInput(effectiveBudget) ?? undefined,
      include_cards: [],
      exclude_cards: [],
      archetype_recipes: [],
      rounds: 8,
      proposals_per_round: 3,
      sim_runs_per_eval: 100
    });
  }

  return (
    <div className="builder workflow-layout">
      <section className="form-grid" aria-label="Generate deck controls">
        <FormatColorPicker format={format} colors={colors} onFormatChange={setFormat} onColorsChange={setColors} />
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
        <GenerateForm
          expertMode={expertMode}
          onExpertModeChange={setExpertMode}
          budget={budget}
          onBudgetChange={setBudget}
          prompt={prompt}
          onPromptChange={setPrompt}
          onSubmit={() => void handleGenerate()}
          loading={generator.loading}
        />
      </section>

      <section className="results-grid" aria-label="Generated deck output" aria-live="polite">
        <WorkflowSummary
          title={deck?.title ?? "Competitive deck output appears here"}
          summary={deck?.strategy_summary ?? "Set your constraints and generate a deck with legality, evidence, and quality reported separately."}
          dataStatus={dataStatus}
          error={generator.error}
          score={deck?.score}
          price={deck?.estimated_price_usd}
          legality={deck ? {
            isLegal: deck.is_legal,
            errorCount: deck.validation_errors.length,
            warningCount: deck.warnings.length
          } : undefined}
        />

        {deck ? (
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
              loading={generator.loading}
            />
            {deckDiff ? <div className="panel results-card"><DeckDiffView diff={deckDiff} /></div> : null}
            <div className="panel results-card">
              <div className="evaluation-heading">
                <div>
                  <div className="optimizer-title">Simulation verdict</div>
                  <div className="muted optimizer-copy">Measure resilience, flood/screw, inevitability, and confidence-interval win rate.</div>
                </div>
                <div className="chips">
                  <button type="button" className="chip" onClick={() => setExpertMode(!expertMode)} aria-pressed={expertMode}>
                    {expertMode ? "Expert view" : "Beginner view"}
                  </button>
                  <button type="button" className="chip active" onClick={() => void evaluation.evaluate(deck.format, deck.mainboard)} disabled={evaluation.loading}>
                    {evaluation.loading ? "Evaluating…" : "Evaluate deck"}
                  </button>
                </div>
              </div>
              {evaluation.error ? <p className="workflow-error" role="alert">{evaluation.error}</p> : null}
              {evaluation.evaluation ? <div className="evaluation-output"><DeckEvaluationPanel evaluation={evaluation.evaluation} detailed={expertMode} /></div> : null}
            </div>
            {format === "modern" ? (
              <RationalePanel
                rationale={rationale.rationale}
                sideboard={rationale.sideboard}
                status={rationale.status}
                error={rationale.error}
                onRequest={handleRequestRationale}
                onReset={rationale.reset}
              />
            ) : null}
          </>
        ) : null}
      </section>

      {cardDetail.card ? (
        <CardDetailModal card={cardDetail.card} loading={cardDetail.loading} error={cardDetail.error} onClose={cardDetail.close} />
      ) : null}
    </div>
  );
}
