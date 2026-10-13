"use client";

import { useEffect, useState } from "react";

export type ProgressStage = {
  label: string;
  /** Seconds after the start when this stage is shown as active. */
  startsAt: number;
};

export const GENERATE_STAGES: ProgressStage[] = [
  { label: "Parsing your constraints", startsAt: 0 },
  { label: "Retrieving archetype shells", startsAt: 1.5 },
  { label: "Evaluating candidate lists", startsAt: 4 },
  { label: "Tuning the mana base", startsAt: 8 },
  { label: "Writing the explanation", startsAt: 12 }
];

export const REFINE_STAGES: ProgressStage[] = [
  { label: "Reading your change request", startsAt: 0 },
  { label: "Rebuilding the list", startsAt: 2 },
  { label: "Re-checking legality and mana", startsAt: 6 },
  { label: "Writing what changed", startsAt: 10 }
];

type Props = {
  active: boolean;
  title: string;
  stages: ProgressStage[];
};

/**
 * Staged progress while a request is in flight. The API reports no progress,
 * so stages advance on a timer; the last stage holds until the response lands.
 * Only the current stage label is announced (role="status").
 */
export function GenerationProgress({ active, title, stages }: Props) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!active) {
      setElapsed(0);
      return;
    }
    const started = Date.now();
    setElapsed(0);
    const timer = setInterval(() => setElapsed((Date.now() - started) / 1000), 250);
    return () => clearInterval(timer);
  }, [active]);

  if (!active) return null;

  let currentIndex = 0;
  stages.forEach((stage, index) => {
    if (elapsed >= stage.startsAt) currentIndex = index;
  });
  const lastStart = stages[stages.length - 1]?.startsAt ?? 1;
  // Ease toward 95% so the bar never claims to be finished early.
  const percent = Math.min(95, Math.round((Math.min(elapsed, lastStart + 8) / (lastStart + 8)) * 95));

  return (
    <div className="panel results-card generation-progress">
      <div className="generation-progress-head">
        <span className="optimizer-title">{title}</span>
        <span className="muted generation-progress-time">{Math.floor(elapsed)}s</span>
      </div>
      <div className="generation-progress-bar" aria-hidden="true">
        <div className="generation-progress-fill" style={{ width: `${percent}%` }} />
      </div>
      <ol className="generation-stages">
        {stages.map((stage, index) => {
          const state = index < currentIndex ? "done" : index === currentIndex ? "current" : "pending";
          return (
            <li key={stage.label} className={`generation-stage ${state}`} aria-current={state === "current" ? "step" : undefined}>
              <span className="generation-stage-dot" aria-hidden="true" />
              <span>{stage.label}</span>
            </li>
          );
        })}
      </ol>
      <p className="sr-only" role="status">
        {stages[currentIndex]?.label}…
      </p>
    </div>
  );
}
