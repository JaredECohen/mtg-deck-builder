"use client";

import { useEffect, useRef, useState } from "react";

import { AnalysisResults } from "./analysis-results";
import { AnalyzeForm, type ManualZone } from "./analyze-form";
import { FormatColorPicker } from "./format-color-picker";
import { WorkflowSummary } from "./workflow-summary";
import type { CardContext } from "@/hooks/use-card-detail";
import { useDeckAnalyzer } from "@/hooks/use-deck-analyzer";
import { fetchSharedDeck } from "@/lib/api";
import {
  planExampleResultReveal,
  prepopulateFromExample,
  resolveAnalyzeSeed,
  shouldAutoAnalyzeArrival,
  type ExampleDeck,
} from "@/lib/example-decks";
import { clearManualDraft, loadManualDraft, saveManualDraft } from "@/lib/manual-draft";
import type { CardRef, DataStatusResponse, FormatName } from "@/lib/types";

const DEFAULT_NOTES = "Tell me how this deck plays, what shell it resembles, and what I should improve.";

/** True when focus is in a field the user is typing in, so a late result must not move it. */
export function isEditingFormControl(element: Element | null): boolean {
  if (!(element instanceof HTMLElement)) return false;
  const tag = element.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  return element.isContentEditable;
}

type Props = {
  dataStatus: DataStatusResponse | null;
  onOpenCard: (name: string, context?: CardContext) => void;
  /** Share token from ?deck=: load that saved deck and analyze it. */
  sharedToken: string | null;
  /** Official list id from ?example=: prefill the editor from the guide catalog. */
  exampleId?: string | null;
  /** Server-resolved list, so the first HTML already contains the cards. */
  initialExample?: ExampleDeck | null;
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

export function AnalyzeWorkflow({ dataStatus, onOpenCard, sharedToken, exampleId, initialExample = null }: Props) {
  const seeded =
    initialExample && exampleId
      ? resolveAnalyzeSeed({
          example: {
            format: initialExample.format,
            mainboard: initialExample.mainboard,
            sideboard: initialExample.sideboard,
            commander: initialExample.commander,
            name: initialExample.name,
            note: initialExample.note ?? "",
          },
          draft: null,
          defaultNotes: DEFAULT_NOTES,
        })
      : null;
  const [format, setFormat] = useState<FormatName | null>(seeded?.format ?? null);
  const [manualMainboard, setManualMainboard] = useState<CardRef[]>(seeded?.mainboard ?? []);
  const [manualSideboard, setManualSideboard] = useState<CardRef[]>(seeded?.sideboard ?? []);
  const [manualCommander, setManualCommander] = useState(seeded?.commander ?? "");
  const [manualNotes, setManualNotes] = useState(seeded?.notes ?? DEFAULT_NOTES);
  const [manualImportText, setManualImportText] = useState("");
  const [deepAnalysis, setDeepAnalysis] = useState(false);
  const [draftHydrated, setDraftHydrated] = useState(false);
  // The list the current analysis was run on; edits after that mark it stale.
  const [analyzedKey, setAnalyzedKey] = useState<string | null>(null);
  const [shared, setShared] = useState<{ status: "loading" | "loaded" | "failed"; name?: string; error?: string } | null>(null);
  const [statusMessage, setStatusMessage] = useState("");
  // Set only after ?example= actually fills the editor. A failed load leaves this null.
  const [loadedExampleId, setLoadedExampleId] = useState<string | null>(seeded && exampleId ? exampleId : null);
  const loadedToken = useRef<string | null>(null);
  // ?example= fills the editor from the catalog. That load must not replace the
  // saved draft, and the draft must not replace the example.
  const persistDraft = useRef(!seeded);
  // Claimed when an example auto-analyze actually starts, so a later render
  // (or React strict mode's second effect) cannot fire a second request.
  const autoAnalyzeClaim = useRef<string | null>(null);
  const resultsRef = useRef<HTMLElement | null>(null);
  // Example id whose results we already tried to reveal. A later example can reveal again.
  const revealedExampleId = useRef<string | null>(null);

  const analyzer = useDeckAnalyzer();
  const analysis = analyzer.analysis;
  const { analyze, reset: resetAnalyzer } = analyzer;

  useEffect(() => {
    let cancelled = false;
    // A shared link replaces the local draft instead of merging with it.
    // The example list is fetched only when ?example= is present.
    async function hydrate() {
      if (sharedToken) {
        if (!cancelled) setDraftHydrated(true);
        return;
      }
      // The server already filled the editor. Don't import the catalog again
      // and don't let a saved draft replace that list.
      if (seeded) {
        persistDraft.current = false;
        if (!cancelled) setDraftHydrated(true);
        return;
      }
      let example = null;
      if (exampleId) {
        try {
          example = await prepopulateFromExample(exampleId);
        } catch {
          // The list chunk failed. Drop the example and keep the saved draft.
          example = null;
        }
      }
      if (cancelled) return;
      const seed = resolveAnalyzeSeed({
        example,
        draft: loadManualDraft(),
        defaultNotes: DEFAULT_NOTES,
      });
      persistDraft.current = seed.persistDraft;
      if (seed.format) setFormat(seed.format);
      setManualMainboard(seed.mainboard);
      setManualSideboard(seed.sideboard);
      setManualCommander(seed.commander);
      setManualNotes(seed.notes);
      setLoadedExampleId(example && exampleId ? exampleId : null);
      setDraftHydrated(true);
    }
    void hydrate();
    return () => {
      cancelled = true;
    };
    // Only on mount: later token changes are handled by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!draftHydrated || !persistDraft.current) return;
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
    if (persistDraft.current) clearManualDraft();
  }

  function runAnalysis(options: { deepAnalysis: boolean }) {
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
      deep_analysis: options.deepAnalysis
    });
  }

  function handleAnalyze() {
    runAnalysis({ deepAnalysis });
  }

  // Same list as the Analyze button, but the automatic run is always heuristic.
  // The Deep analysis checkbox can flip while the example list is loading, and
  // that must not spend a Claude call. The timeout is cleared on cleanup so
  // React 19 strict mode's double-invoked effect starts the request once.
  const runAutoAnalyze = useRef(runAnalysis);
  runAutoAnalyze.current = runAnalysis;
  useEffect(() => {
    const id = loadedExampleId;
    if (!shouldAutoAnalyzeArrival({
      exampleId: id,
      exampleResolved: Boolean(id),
      sharedToken,
      formatReady: Boolean(format)
    })) return;
    if (!id || autoAnalyzeClaim.current === id) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (cancelled || autoAnalyzeClaim.current === id) return;
      autoAnalyzeClaim.current = id;
      runAutoAnalyze.current({ deepAnalysis: false });
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [loadedExampleId, sharedToken, format, manualMainboard, manualSideboard, manualCommander, manualNotes]);

  // After that automatic run, bring off-screen results up on a phone. Skip it
  // when the summary is already in view, and never steal focus from a field
  // the user is editing while the request is in flight. The example id is
  // recorded only once we actually reveal, so leaving the field can still scroll.
  useEffect(() => {
    if (!loadedExampleId || analyzer.loading) return;
    if (!analysis && !analyzer.error) return;

    const tryReveal = () => {
      const node = resultsRef.current;
      const rect = node?.getBoundingClientRect();
      const inView = Boolean(rect && rect.top >= 0 && rect.top < window.innerHeight * 0.85);
      const plan = planExampleResultReveal({
        alreadyRevealed: revealedExampleId.current === loadedExampleId,
        editing: isEditingFormControl(document.activeElement),
        hasResultsNode: Boolean(node),
        inView,
      });
      if (plan === "done" || plan === "wait") return;
      revealedExampleId.current = loadedExampleId;
      if (plan === "mark" || !node) return;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      node.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      node.focus({ preventScroll: true });
    };

    tryReveal();
    if (revealedExampleId.current === loadedExampleId) return;
    const onFocusOut = () => {
      window.setTimeout(tryReveal, 0);
    };
    document.addEventListener("focusout", onFocusOut);
    return () => document.removeEventListener("focusout", onFocusOut);
  }, [loadedExampleId, analysis, analyzer.loading, analyzer.error]);

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

      <section
        ref={resultsRef}
        className="results-grid analysis-output"
        aria-label="Deck analysis output"
        aria-busy={analyzer.loading}
        tabIndex={-1}
      >
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
