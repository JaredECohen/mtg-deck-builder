"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AnalyzeWorkflow } from "./workshop/analyze-workflow";
import { CardDetailModal } from "./workshop/card-detail-modal";
import { GenerateWorkflow } from "./workshop/generate-workflow";
import { PreconUpgrade } from "./workshop/precon-upgrade";
import { panelId, tabId, Tabs } from "./workshop/tabs";
import { useCardDetail } from "@/hooks/use-card-detail";
import { useDataStatus } from "@/hooks/use-data-status";

type BuilderMode = "generate" | "analyze" | "precon";

const MODE_TABS = [
  { id: "generate" as const, label: "Generate a deck" },
  { id: "analyze" as const, label: "Analyze my deck" },
  { id: "precon" as const, label: "Upgrade a precon" }
];

export function DeckWorkshop() {
  // ?deck=<share_token> opens a shared deck in the Analyze workflow.
  const searchParams = useSearchParams();
  const sharedToken = searchParams.get("deck");
  const [mode, setMode] = useState<BuilderMode>(sharedToken ? "analyze" : "generate");

  // Shared by both workflows, so the data-status request and the card modal
  // exist once on the page.
  const dataStatus = useDataStatus();
  const cardDetail = useCardDetail();

  useEffect(() => {
    if (sharedToken) setMode("analyze");
  }, [sharedToken]);

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
        <AnalyzeWorkflow dataStatus={dataStatus} onOpenCard={cardDetail.open} sharedToken={sharedToken} />
      </div>
      <div id={panelId("workshop", "precon")} role="tabpanel" aria-labelledby={tabId("workshop", "precon")} hidden={mode !== "precon"}>
        <PreconUpgrade onOpenCard={cardDetail.open} />
      </div>

      <CardDetailModal detail={cardDetail} />
    </section>
  );
}
