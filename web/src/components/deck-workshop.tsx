"use client";

import { useLayoutEffect, useState } from "react";

import { AnalyzeWorkflow } from "./workshop/analyze-workflow";
import { CardDetailModal } from "./workshop/card-detail-modal";
import { GenerateWorkflow } from "./workshop/generate-workflow";
import { PreconUpgrade } from "./workshop/precon-upgrade";
import { panelId, tabId, Tabs } from "./workshop/tabs";
import { useCardDetail } from "@/hooks/use-card-detail";
import { useDataStatus } from "@/hooks/use-data-status";
import { TCG_SUB_ID } from "@/lib/affiliate";

type BuilderMode = "generate" | "analyze" | "precon";

const MODE_TABS = [
  { id: "generate" as const, label: "Generate a deck" },
  { id: "analyze" as const, label: "Analyze my deck" },
  { id: "precon" as const, label: "Upgrade a precon" }
];

export function DeckWorkshop() {
  // The static homepage always paints the generate tab. A shared deck or an
  // official example switches to Analyze before the browser paints. Reading
  // the URL here keeps the shell static; the search-params hook would bail it
  // out to an empty fallback.
  const [mode, setMode] = useState<BuilderMode>("generate");

  // Shared by both workflows, so the data-status request and the card modal
  // exist once on the page.
  const dataStatus = useDataStatus();
  const cardDetail = useCardDetail();

  useLayoutEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("deck")?.trim() || params.get("example")?.trim()) setMode("analyze");
  }, []);

  return (
    <section className="workshop-root" aria-label="MTG deck workshop">
      <div className="panel panel-strong workshop-mode-bar">
        <div>
          <div className="eyebrow">Start here</div>
          <div className="workshop-mode-title">What do you want to do?</div>
        </div>
        <Tabs items={MODE_TABS} selected={mode} onSelect={setMode} label="Workshop mode" idPrefix="workshop" />
      </div>

      <div id={panelId("workshop", "generate")} role="tabpanel" aria-labelledby={tabId("workshop", "generate")} hidden={mode !== "generate"}>
        <GenerateWorkflow dataStatus={dataStatus} onOpenCard={cardDetail.open} />
      </div>
      <div id={panelId("workshop", "analyze")} role="tabpanel" aria-labelledby={tabId("workshop", "analyze")} hidden={mode !== "analyze"}>
        <AnalyzeWorkflow dataStatus={dataStatus} onOpenCard={cardDetail.open} />
      </div>
      <div id={panelId("workshop", "precon")} role="tabpanel" aria-labelledby={tabId("workshop", "precon")} hidden={mode !== "precon"}>
        <PreconUpgrade onOpenCard={cardDetail.open} />
      </div>

      <CardDetailModal
        detail={cardDetail}
        subId={mode === "precon" ? TCG_SUB_ID.workshopPrecon : TCG_SUB_ID.workshop}
      />
    </section>
  );
}
