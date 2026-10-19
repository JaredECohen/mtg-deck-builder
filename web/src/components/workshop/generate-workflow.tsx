"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { CommanderPicker, type CommanderMode } from "./commander-picker";
import { DeckEvaluationPanel } from "./deck-evaluation-panel";
import { DeckResults } from "./deck-results";
import { DEFAULT_EXPERT_SETTINGS, type ExpertSettings } from "./expert-controls";
import { FormatColorPicker } from "./format-color-picker";
import { GenerateForm } from "./generate-form";
import { GENERATE_STAGES, GenerationProgress, REFINE_STAGES } from "./generation-progress";
import { RationalePanel } from "./rationale-panel";
import { SaveSharePanel } from "./save-share-panel";
import { StrategyPicker } from "./strategy-picker";
import { WorkflowSummary } from "./workflow-summary";
import type { CardContext } from "@/hooks/use-card-detail";
import type { CommanderSort } from "@/hooks/use-commander-search";
import { useDeckEvaluation } from "@/hooks/use-deck-evaluation";
import { useDeckGenerator } from "@/hooks/use-deck-generator";
import { useDeckRationale } from "@/hooks/use-deck-rationale";
import { useExperienceMode } from "@/hooks/use-experience-mode";
import { MAX_PROMPT_CHARS, type GenerateDeckInput } from "@/lib/api";
import { parseCardNameLines } from "@/lib/briefs";
import { cardCount, diffCardLists } from "@/lib/deck-diff";
import { loadRefineDraft, saveRefineDraft } from "@/lib/manual-draft";
import { activeTags, parseBudgetInput, type StrategyId } from "@/lib/strategies";
import type { CommanderProfile, DataStatusResponse, DeckAlternative, FormatName } from "@/lib/types";

const DEFAULT_REFINE_PROMPT = "Make it a bit cheaper without losing too much pressure.";
const FORMAT_LABEL: Record<FormatName, string> = {
  standard: "Standard",
  modern: "Modern",
  pioneer: "Pioneer",
  legacy: "Legacy",
  commander: "Commander"
};

function colorKey(colors: string[]): string {
  return [...colors].sort().join("");
}

type Props = {
  dataStatus: DataStatusResponse | null;
  onOpenCard: (name: string, context?: CardContext) => void;
};

export function GenerateWorkflow({ dataStatus, onOpenCard }: Props) {
  const [format, setFormat] = useState<FormatName>("modern");
  // Nothing is preselected: colors, strategies and the brief start empty so
  // the first deck reflects only what the user chose.
  const [colors, setColors] = useState<string[]>([]);
  const [selectedStrategies, setSelectedStrategies] = useState<StrategyId[]>([]);
  const [prompt, setPrompt] = useState("");
  const searchParams = useSearchParams();

  // Guide links open the builder pre-filled: /?format=commander&brief=...
  useEffect(() => {
    const linkedFormat = searchParams.get("format");
    if (linkedFormat && linkedFormat in FORMAT_LABEL) setFormat(linkedFormat as FormatName);
    const linkedBrief = searchParams.get("brief");
    if (linkedBrief) setPrompt(linkedBrief.slice(0, MAX_PROMPT_CHARS));
    // Only on arrival: later edits belong to the user.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [refinePrompt, setRefinePrompt] = useState(DEFAULT_REFINE_PROMPT);
  const [refineDraftLoaded, setRefineDraftLoaded] = useState(false);
  const [expertSettings, setExpertSettings] = useState<ExpertSettings>(DEFAULT_EXPERT_SETTINGS);
  const [commanderMode, setCommanderMode] = useState<CommanderMode>("recommend");
  const [commanderSort, setCommanderSort] = useState<CommanderSort>("match");
  const [commanderSearch, setCommanderSearch] = useState("");
  const [selectedCommanderName, setSelectedCommanderName] = useState("");
  const [selectedCommanderProfile, setSelectedCommanderProfile] = useState<CommanderProfile | null>(null);
  const [statusMessage, setStatusMessage] = useState("");

  const experience = useExperienceMode();
  const expertMode = experience.detailed;
  const setExpertMode = (value: boolean) => experience.setMode(value ? "expert" : "beginner");
  const generator = useDeckGenerator();
  const rationale = useDeckRationale();
  const evaluation = useDeckEvaluation();
  const tags = useMemo(() => activeTags(selectedStrategies), [selectedStrategies]);
  const deck = generator.deck;
  const current = generator.current;

  useEffect(() => {
    if (format !== "commander") {
      setSelectedCommanderProfile(null);
      setSelectedCommanderName("");
    }
  }, [format]);

  useEffect(() => {
    if (selectedCommanderProfile) setColors(selectedCommanderProfile.colors);
  }, [selectedCommanderProfile]);

  useEffect(() => {
    const stored = loadRefineDraft();
    if (stored !== null) setRefinePrompt(stored);
    setRefineDraftLoaded(true);
  }, []);

  useEffect(() => {
    if (refineDraftLoaded) saveRefineDraft(refinePrompt);
  }, [refinePrompt, refineDraftLoaded]);

  // Simulator results describe one exact list; any deck change (refine, undo,
  // restore, new build) clears them so they can't describe a different deck.
  const { reset: resetRationale } = rationale;
  const { reset: resetEvaluation } = evaluation;
  useEffect(() => {
    resetRationale();
    resetEvaluation();
  }, [deck, resetRationale, resetEvaluation]);

  // One concise announcement per new deck instead of a live region over the
  // whole results column.
  useEffect(() => {
    if (!current) {
      setStatusMessage("");
      return;
    }
    const verb = current.kind === "generate" ? "Deck ready" : "Deck updated";
    setStatusMessage(`${verb}: ${current.deck.title}, ${cardCount(current.deck.mainboard)} cards.`);
  }, [current]);

  function handleFormatChange(next: FormatName) {
    setFormat(next);
  }

  /** Builds the request from the form. Beginners send no expert fields at all. */
  function buildInput(): GenerateDeckInput | string {
    const base: GenerateDeckInput = {
      format,
      colors,
      commander_name: format === "commander" && commanderMode === "selected" ? selectedCommanderName : undefined,
      playstyle_tags: tags.playstyle,
      theme_tags: tags.theme,
      experience_level: expertMode ? "expert" : "beginner",
      prompt
    };
    if (format === "commander" && commanderMode === "selected" && !selectedCommanderName) {
      return "Select a commander before building from your pick.";
    }
    if (!expertMode) return base;
    const budget = parseBudgetInput(expertSettings.budget);
    if (expertSettings.budget.trim() && budget === undefined) return "Budget must be a non-negative number.";
    return {
      ...base,
      budget,
      mode: expertSettings.mode,
      match_type: format === "commander" ? undefined : expertSettings.matchType,
      bracket: format === "commander" ? expertSettings.bracket : null,
      include_cards: expertSettings.includeCards,
      exclude_cards: expertSettings.excludeCards,
      owned_cards: parseCardNameLines(expertSettings.ownedText)
    };
  }

  async function handleGenerate() {
    const input = buildInput();
    if (typeof input === "string") {
      generator.setError(input);
      return;
    }
    await generator.generate(input);
  }

  async function handleBuildAlternative(alternative: DeckAlternative) {
    // Same constraints as the deck on screen; only the shell changes.
    const base = generator.lastInput ?? buildInput();
    if (typeof base === "string") {
      generator.setError(base);
      return;
    }
    await generator.generate({
      ...base,
      archetype_name: alternative.name,
      commander_name: alternative.commander ?? base.commander_name
    });
  }

  async function handleRefine() {
    if (!refinePrompt.trim()) return;
    await generator.refine(refinePrompt);
  }

  function handleRequestRationale() {
    if (!deck || deck.format !== "modern") return;
    // Seed the optimizer with the list on screen so its rationale describes it.
    void rationale.submit({
      format: "modern",
      colors: deck.colors,
      deck_size: 60,
      budget_usd: deck.constraints?.budget ?? undefined,
      include_cards: [...new Set(deck.mainboard.map((card) => card.name))],
      exclude_cards: deck.constraints?.exclude_cards ?? [],
      archetype_recipes: [],
      rounds: 8,
      proposals_per_round: 3,
      sim_runs_per_eval: 100
    });
  }

  // The deck on screen was built from different settings than the form now shows.
  const lastInput = generator.lastInput;
  const builtFor =
    deck && lastInput && (lastInput.format !== format || colorKey(lastInput.colors) !== colorKey(colors))
      ? `${FORMAT_LABEL[lastInput.format]}${lastInput.colors.length ? ` (${lastInput.colors.join("/")})` : ""}`
      : null;

  // What the latest refine changed: the API's diff, or a local one as a fallback.
  const previous = generator.revisions.length > 1 ? generator.revisions[generator.revisions.length - 2] : null;
  const changes =
    current?.kind === "refine" ? current.deck.changes ?? (previous ? diffCardLists(previous.deck.mainboard, current.deck.mainboard) : null) : null;

  const openDeckCard = (name: string) =>
    onOpenCard(name, deck ? { format: deck.format, colors: deck.colors } : { format });

  return (
    <div className="builder workflow-layout">
      <section className="form-grid" aria-label="Generate deck controls">
        <FormatColorPicker format={format} colors={colors} onFormatChange={handleFormatChange} onColorsChange={setColors} />
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
          onOpenCard={(name) => onOpenCard(name, { format: "commander" })}
          onProfileChange={setSelectedCommanderProfile}
        />
        <StrategyPicker selected={selectedStrategies} onChange={setSelectedStrategies} />
        <GenerateForm
          format={format}
          expertMode={expertMode}
          onExpertModeChange={setExpertMode}
          expertSettings={expertSettings}
          onExpertSettingsChange={setExpertSettings}
          prompt={prompt}
          onPromptChange={(value) => setPrompt(value)}
          onSubmit={() => void handleGenerate()}
          loading={generator.loading}
        />
      </section>

      <section className="results-grid" aria-label="Generated deck output" aria-busy={generator.loading}>
        <p className="sr-only" role="status">{statusMessage}</p>
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
          badge={
            builtFor ? (
              <div className="stale-banner" role="note">
                <span>
                  Built for <strong>{builtFor}</strong>. Your settings changed; regenerate to apply them.
                </span>
                <button type="button" className="chip" onClick={() => void handleGenerate()} disabled={generator.loading}>
                  Regenerate
                </button>
              </div>
            ) : null
          }
        />

        <GenerationProgress
          active={generator.loading}
          title={generator.action === "refine" ? "Refining your deck" : "Building your deck"}
          stages={generator.action === "refine" ? REFINE_STAGES : GENERATE_STAGES}
        />

        {deck ? (
          <>
            <DeckResults
              deck={deck}
              meta={generator.meta}
              metaError={generator.metaError}
              selectedCommanderName={selectedCommanderName}
              selectedCommanderProfile={selectedCommanderProfile}
              refinePrompt={refinePrompt}
              onRefinePromptChange={setRefinePrompt}
              onRefine={() => void handleRefine()}
              onOpenCard={openDeckCard}
              loading={generator.loading}
              expertMode={expertMode}
              changes={changes}
              revisions={generator.revisions}
              onUndo={generator.undo}
              onRestore={generator.restore}
              onApplyOptimized={(next) => generator.applyDeck(next, "Applied sim-optimized version")}
              onBuildAlternative={(alternative) => void handleBuildAlternative(alternative)}
            />
            <SaveSharePanel deck={deck} evaluation={evaluation.evaluation} />
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
                  <button
                    type="button"
                    className="chip active"
                    onClick={() =>
                      void evaluation.evaluate(deck.format, deck.mainboard, { sideboard: deck.sideboard, commander: deck.commander })
                    }
                    disabled={evaluation.loading}
                  >
                    {evaluation.loading ? "Evaluating…" : "Evaluate deck"}
                  </button>
                </div>
              </div>
              {evaluation.error ? <p className="workflow-error" role="alert">{evaluation.error}</p> : null}
              {evaluation.evaluation ? <div className="evaluation-output"><DeckEvaluationPanel evaluation={evaluation.evaluation} detailed={expertMode} /></div> : null}
            </div>
            {deck.format === "modern" ? (
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
    </div>
  );
}
