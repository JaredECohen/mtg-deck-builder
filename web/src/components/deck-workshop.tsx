"use client";

import { useEffect, useState } from "react";

import { AnalyzeWorkflow } from "./workshop/analyze-workflow";
import { CardDetailModal } from "./workshop/card-detail-modal";
import { GenerateWorkflow } from "./workshop/generate-workflow";
import { PreconUpgrade } from "./workshop/precon-upgrade";
import { panelId, tabId, Tabs } from "./workshop/tabs";
import { useCardDetail } from "@/hooks/use-card-detail";
import { useDataStatus } from "@/hooks/use-data-status";
import type { ExampleDeck } from "@/lib/example-decks";

type BuilderMode = "generate" | "analyze" | "precon";

const MODE_TABS = [
  { id: "generate" as const, label: "Generate a deck" },
  { id: "analyze" as const, label: "Analyze my deck" },
  { id: "precon" as const, label: "Upgrade a precon" }
];

export function DeckWorkshop({
  sharedToken,
  exampleId,
  linkedFormat,
  linkedBrief,
  initialExample,
}: {
  sharedToken: string | null;
  exampleId: string | null;
  linkedFormat: string | null;
  linkedBrief: string | null;
  initialExample: ExampleDeck | null;
}) {
  // ?deck= and ?example= open the Analyze workflow. The server passes them
  // so the first HTML already has the right tab.
  const [mode, setMode] = useState<BuilderMode>(sharedToken || exampleId ? "analyze" : "generate");

  // Shared by both workflows, so the data-status request and the card modal
  // exist once on the page.
  const dataStatus = useDataStatus();
  const cardDetail = useCardDetail();

  useEffect(() => {
    if (sharedToken || exampleId) setMode("analyze");
  }, [sharedToken, exampleId]);

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
        <GenerateWorkflow
          dataStatus={dataStatus}
          onOpenCard={cardDetail.open}
          linkedFormat={linkedFormat}
          linkedBrief={linkedBrief}
        />
      </div>
      <div id={panelId("workshop", "analyze")} role="tabpanel" aria-labelledby={tabId("workshop", "analyze")} hidden={mode !== "analyze"}>
        <AnalyzeWorkflow
          dataStatus={dataStatus}
          onOpenCard={cardDetail.open}
          sharedToken={sharedToken}
          exampleId={exampleId}
          initialExample={initialExample}
        />
      </div>
      <div id={panelId("workshop", "precon")} role="tabpanel" aria-labelledby={tabId("workshop", "precon")} hidden={mode !== "precon"}>
        <PreconUpgrade onOpenCard={cardDetail.open} />
      </div>

      <CardDetailModal detail={cardDetail} />
    </section>
  );
}
