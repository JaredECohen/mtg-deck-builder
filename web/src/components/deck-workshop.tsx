"use client";

import { useState } from "react";

import { AnalyzeWorkflow } from "./workshop/analyze-workflow";
import { GenerateWorkflow } from "./workshop/generate-workflow";

type BuilderMode = "generate" | "analyze";

export function DeckWorkshop() {
  const [mode, setMode] = useState<BuilderMode>("generate");

  return (
    <section className="workshop-root" aria-label="MTG deck workshop">
      <div className="panel panel-strong workshop-mode-bar">
        <div>
          <div className="eyebrow">Start here</div>
          <div className="workshop-mode-title">What do you want to do?</div>
        </div>
        <div className="chips" role="tablist" aria-label="Workshop mode">
          <button
            type="button"
            role="tab"
            id="generate-tab"
            aria-controls="generate-workflow"
            aria-selected={mode === "generate"}
            className={`chip ${mode === "generate" ? "active" : ""}`}
            onClick={() => setMode("generate")}
          >
            Generate a deck
          </button>
          <button
            type="button"
            role="tab"
            id="analyze-tab"
            aria-controls="analyze-workflow"
            aria-selected={mode === "analyze"}
            className={`chip ${mode === "analyze" ? "active" : ""}`}
            onClick={() => setMode("analyze")}
          >
            Analyze my deck
          </button>
        </div>
      </div>

      <div id="generate-workflow" role="tabpanel" aria-labelledby="generate-tab" hidden={mode !== "generate"}>
        <GenerateWorkflow />
      </div>
      <div id="analyze-workflow" role="tabpanel" aria-labelledby="analyze-tab" hidden={mode !== "analyze"}>
        <AnalyzeWorkflow />
      </div>
    </section>
  );
}
