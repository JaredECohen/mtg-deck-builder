"use client";

import { useEffect, useRef, useState } from "react";

import { AnalysisResults } from "./analysis-results";
import { AnalyzeForm, type ManualZone } from "./analyze-form";
import { FormatColorPicker } from "./format-color-picker";
import { WorkflowSummary } from "./workflow-summary";
import type { CardContext } from "@/hooks/use-card-detail";
import { useDeckAnalyzer } from "@/hooks/use-deck-analyzer";
import { fetchSharedDeck } from "@/lib/api";
import { clearManualDraft, loadManualDraft, saveManualDraft } from "@/lib/manual-draft";
import type { CardRef, DataStatusResponse, FormatName } from "@/lib/types";

const DEFAULT_NOTES = "Tell me how this deck plays, what shell it resembles, and what I should improve.";

type Props = {
  dataStatus: DataStatusResponse | null;
  onOpenCard: (name: string, context?: CardContext) => void;
  /** Share token from ?deck=: load that saved deck and analyze it. */
  sharedToken: string | null;
};

type Snapshot = { format: FormatName | null; mainboard: CardRef[]; sideboard: CardRef[]; commander: string };

function snapshotKey(snapshot: Snapshot): string {
  const list = (cards: CardRef[]) =>
    [...cards]
      .map((card) => `${card.quantity}:${card.name}`)
      .sort()
      .join("|");
  return [snapshot.format, snapshot.commander, list(snapshot.mainboard), list(snapshot.sideboard)].join("#");
}

export function AnalyzeWorkflow({ dataStatus, onOpenCard, sharedToken }: Props) {
  const [format, setFormat] = useState<FormatName | null>(null);
  const [manualMainboard, setManualMainboard] = useState<CardRef[]>([]);
  const [manualSideboard, setManualSideboard] = useState<CardRef[]>([]);
  const [manualCommander, setManualCommander] = useState("");
  const [manualNotes, setManualNotes] = useState(DEFAULT_NOTES);
  const [manualImportText, setManualImportText] = useState("");
  const [deepAnalysis, setDeepAnalysis] = useState(false);
  const [draftHydrated, setDraftHydrated] = useState(false);
  // The list the current analysis was run on; edits after that mark it stale.
  const [analyzedKey, setAnalyzedKey] = useState<string | null>(null);
  const [shared, setShared] = useState<{ status: "loading" | "loaded" | "failed"; name?: string; error?: string } | null>(null);
  const [statusMessage, setStatusMessage] = useState("");
  const loadedToken = useRef<string | null>(null);

  const analyzer = useDeckAnalyzer();
  const analysis = analyzer.analysis;
  const { analyze, reset: resetAnalyzer } = analyzer;

  useEffect(() => {
    // A shared link replaces the local draft instead of merging with it.
    if (sharedToken) {
      setDraftHydrated(true);
      return;
    }
    const draft = loadManualDraft();
    if (draft?.format) setFormat(draft.format);
    if (draft?.mainboard) setManualMainboard(draft.mainboard);
    if (draft?.sideboard) setManualSideboard(draft.sideboard);
    if (draft?.commander) setManualCommander(draft.commander);
    if (draft?.notes) setManualNotes(draft.notes);
    setDraftHydrated(true);
    // Only on mount: later token changes are handled by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!draftHydrated) return;
    saveManualDraft({
      format: format ?? undefined,
      mainboard: manualMainboard,
      sideboard: manualSideboard,
      commander: manualCommander,
      notes: manualNotes
    });
  }, [draftHydrated, format, manualMainboard, manualSideboard, manualCommander, manualNotes]);

  // ?deck=<token>: fetch the shared list, load it into the editor and analyze it.
  useEffect(() => {
    if (!sharedToken || loadedToken.current === sharedToken) return;
    // Marked loaded only on success: a cancelled run (e.g. React's dev-mode
    // double effect) must not block the retry.
    const controller = new AbortController();
    setShared({ status: "loading" });
    void fetchSharedDeck(sharedToken, controller.signal)
      .then((saved) => {
        if (controller.signal.aborted) return;
        loadedToken.current = sharedToken;
        const snapshot: Snapshot = {
          format: saved.format,
          mainboard: saved.mainboard,
          sideboard: saved.format === "commander" ? [] : saved.sideboard,
          commander: saved.commander ?? ""
        };
        setFormat(snapshot.format);
        setManualMainboard(snapshot.mainboard);
        setManualSideboard(snapshot.sideboard);
        setManualCommander(snapshot.commander);
        setManualImportText("");
        setShared({ status: "loaded", name: saved.name });
        resetAnalyzer();
        setAnalyzedKey(snapshotKey(snapshot));
        // Heuristic analysis only: opening a public link should not spend LLM tokens.
        void analyze({
          format: saved.format,
          commander: snapshot.commander || undefined,
          mainboard: snapshot.mainboard,
          sideboard: snapshot.sideboard,
          notes: DEFAULT_NOTES,
          deep_analysis: false
        });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setShared({ status: "failed", error: err instanceof Error ? err.message : "Shared deck not found" });
      });
    return () => controller.abort();
  }, [sharedToken, analyze, resetAnalyzer]);

  useEffect(() => {
    setStatusMessage(analysis ? `Analysis ready: ${analysis.inferred_archetype}, ${analysis.deck_health}.` : "");
  }, [analysis]);

  const currentKey = snapshotKey({ format, mainboard: manualMainboard, sideboard: manualSideboard, commander: manualCommander });
  const analysisStale = Boolean(analysis && analyzedKey && analyzedKey !== currentKey);

  function updateZone(zone: ManualZone, updater: (cards: CardRef[]) => CardRef[]) {
    if (zone === "mainboard") setManualMainboard((current) => updater(current));
    else setManualSideboard((current) => updater(current));
  }

  function addManualCard(name: string, zone: ManualZone) {
    updateZone(zone, (cards) => {
      const existing = cards.find((item) => item.name === name);
      if (existing) return cards.map((item) => item.name === name ? { ...item, quantity: item.quantity + 1 } : item);
      return [...cards, { name, quantity: 1 }];
    });
  }

  function setManualQuantity(name: string, zone: ManualZone, quantity: number) {
    updateZone(zone, (cards) => {
      if (quantity <= 0) return cards.filter((item) => item.name !== name);
      return cards.map((item) => item.name === name ? { ...item, quantity } : item);
    });
  }

  function moveManualCard(name: string, from: ManualZone) {
    const source = from === "mainboard" ? manualMainboard : manualSideboard;
    if (!source.some((item) => item.name === name)) return;
    setManualQuantity(name, from, 0);
    addManualCard(name, from === "mainboard" ? "sideboard" : "mainboard");
  }

  async function handleImport() {
    if (!format) return;
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
    setManualNotes(DEFAULT_NOTES);
    setAnalyzedKey(null);
    setShared(null);
    analyzer.reset();
    clearManualDraft();
  }

  function handleAnalyze() {
    if (!format) return;
    const snapshot: Snapshot = {
      format,
      mainboard: manualMainboard,
      sideboard: format === "commander" ? [] : manualSideboard,
      commander: format === "commander" ? manualCommander : ""
    };
    setAnalyzedKey(currentKey);
    void analyze({
      format,
      commander: snapshot.commander || undefined,
      mainboard: snapshot.mainboard,
      sideboard: snapshot.sideboard,
      notes: manualNotes,
      deep_analysis: deepAnalysis
    });
  }

  const openCard = (name: string) => onOpenCard(name, { format: format ?? undefined });

  return (
    <div className="builder workflow-layout">
      <section className="form-grid" aria-label="Analyze deck controls">
        {shared ? (
          <div className={`panel form-card shared-deck-note ${shared.status === "failed" ? "import-warning" : ""}`} role="status">
            {shared.status === "loading" ? "Loading the shared deck…" : null}
            {shared.status === "loaded" ? (
              <>
                Loaded shared deck <strong>&ldquo;{shared.name}&rdquo;</strong>. Edit it freely; your changes stay on this device.
              </>
            ) : null}
            {shared.status === "failed" ? `Could not open the shared deck: ${shared.error}` : null}
          </div>
        ) : null}
        <FormatColorPicker
          format={format}
          colors={[]}
          onFormatChange={setFormat}
          onColorsChange={() => undefined}
          showColors={false}
        />
        <AnalyzeForm
          format={format}
          manualMainboard={manualMainboard}
          manualSideboard={manualSideboard}
          manualCommander={manualCommander}
          manualNotes={manualNotes}
          importText={manualImportText}
          loading={analyzer.loading}
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
          onAnalyze={handleAnalyze}
          onOpenCard={openCard}
        />
        {analyzer.warnings.length ? (
          <div className="panel form-card import-warning" role="status">
            <div className="label">Import warnings</div>
            <ul>
              {analyzer.warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}
            </ul>
          </div>
        ) : null}
      </section>

      <section className="results-grid" aria-label="Deck analysis output" aria-busy={analyzer.loading}>
        <p className="sr-only" role="status">{statusMessage}</p>
        <WorkflowSummary
          title={analysis?.inferred_archetype ?? "Manual deck analysis appears here"}
          summary={analysis?.game_plan_summary ?? "Import or edit a list, then assess legality, quality, retrieval evidence, and concrete improvements."}
          dataStatus={dataStatus}
          error={analyzer.error}
          score={analysis?.validation.score}
          health={analysis ? { value: analysis.deck_health, explanation: analysis.deck_health_explanation } : undefined}
          legality={analysis ? {
            isLegal: analysis.validation.is_legal,
            errorCount: analysis.validation.errors.length,
            warningCount: analysis.validation.warnings.length
          } : undefined}
          badge={
            analysisStale ? (
              <div className="stale-banner" role="note">
                <span>The list changed since this analysis.</span>
                <button type="button" className="chip" onClick={handleAnalyze} disabled={analyzer.loading}>
                  Re-analyze
                </button>
              </div>
            ) : null
          }
        />
        {analyzer.loading ? <p className="panel results-card muted">Analyzing the deck…</p> : null}
        {analysis ? (
          <AnalysisResults
            analysis={analysis}
            format={format}
            manualMainboard={manualMainboard}
            manualSideboard={manualSideboard}
            manualCommander={manualCommander}
            onOpenCard={openCard}
          />
        ) : null}
      </section>
    </div>
  );
}
