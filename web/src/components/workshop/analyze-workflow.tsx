"use client";

import { useEffect, useState } from "react";

import { AnalysisResults } from "./analysis-results";
import { AnalyzeForm, type ManualZone } from "./analyze-form";
import { CardDetailModal } from "./card-detail-modal";
import { FormatColorPicker } from "./format-color-picker";
import { WorkflowSummary } from "./workflow-summary";
import { useCardDetail } from "@/hooks/use-card-detail";
import { useDataStatus } from "@/hooks/use-data-status";
import { useDeckAnalyzer } from "@/hooks/use-deck-analyzer";
import { clearManualDraft, loadManualDraft, saveManualDraft } from "@/lib/manual-draft";
import type { CardRef, FormatName } from "@/lib/types";

const DEFAULT_NOTES = "Tell me how this deck plays, what shell it resembles, and what I should improve.";

export function AnalyzeWorkflow() {
  const [format, setFormat] = useState<FormatName>("modern");
  const [manualMainboard, setManualMainboard] = useState<CardRef[]>([]);
  const [manualSideboard, setManualSideboard] = useState<CardRef[]>([]);
  const [manualCommander, setManualCommander] = useState("");
  const [manualNotes, setManualNotes] = useState(DEFAULT_NOTES);
  const [manualImportText, setManualImportText] = useState("");
  const [deepAnalysis, setDeepAnalysis] = useState(true);
  const [draftHydrated, setDraftHydrated] = useState(false);

  const dataStatus = useDataStatus();
  const cardDetail = useCardDetail();
  const analyzer = useDeckAnalyzer();
  const analysis = analyzer.analysis;

  useEffect(() => {
    const draft = loadManualDraft();
    if (draft?.format) setFormat(draft.format);
    if (draft?.mainboard) setManualMainboard(draft.mainboard);
    if (draft?.sideboard) setManualSideboard(draft.sideboard);
    if (draft?.commander) setManualCommander(draft.commander);
    if (draft?.notes) setManualNotes(draft.notes);
    setDraftHydrated(true);
  }, []);

  useEffect(() => {
    if (!draftHydrated) return;
    saveManualDraft({
      format,
      mainboard: manualMainboard,
      sideboard: manualSideboard,
      commander: manualCommander,
      notes: manualNotes
    });
  }, [draftHydrated, format, manualMainboard, manualSideboard, manualCommander, manualNotes]);

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
    analyzer.reset();
    clearManualDraft();
  }

  function handleAnalyze() {
    void analyzer.analyze({
      format,
      commander: format === "commander" ? manualCommander || undefined : undefined,
      mainboard: manualMainboard,
      sideboard: format === "commander" ? [] : manualSideboard,
      notes: manualNotes,
      deep_analysis: deepAnalysis
    });
  }

  return (
    <div className="builder workflow-layout">
      <section className="form-grid" aria-label="Analyze deck controls">
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
          onOpenCard={(name) => void cardDetail.open(name)}
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

      <section className="results-grid" aria-label="Deck analysis output" aria-live="polite">
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
        />
        {analysis ? (
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
        <CardDetailModal card={cardDetail.card} loading={cardDetail.loading} error={cardDetail.error} onClose={cardDetail.close} />
      ) : null}
    </div>
  );
}
