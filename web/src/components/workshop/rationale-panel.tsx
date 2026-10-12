import { DeckRationaleView } from "./deck-rationale";
import type { DeckRationaleData, SideboardPlanData } from "@/lib/types";

type Props = {
  rationale: DeckRationaleData | null;
  sideboard: SideboardPlanData | null;
  status: "idle" | "submitting" | "polling" | "succeeded" | "failed";
  error: string | null;
  onRequest: () => void;
  onReset: () => void;
};

export function RationalePanel({ rationale, sideboard, status, error, onRequest, onReset }: Props) {
  if (status === "idle") {
    return (
      <div className="panel results-card optimizer-panel">
        <div className="optimizer-panel-row">
          <div>
            <div className="optimizer-title">Tournament-grade rationale</div>
            <div className="muted optimizer-copy">
              Run the simulator-driven optimizer for a win plan, mulligan guide, matchup matrix, and critic transcript. About 30 seconds.
            </div>
          </div>
          <button type="button" onClick={onRequest} className="button secondary">Run optimizer</button>
        </div>
      </div>
    );
  }

  if (status === "submitting" || status === "polling") {
    return <div className="panel results-card muted">{status === "submitting" ? "Submitting optimizer job…" : "Optimizer running…"}</div>;
  }

  if (status === "failed") {
    return (
      <div className="panel results-card panel-error" role="alert">
        Optimizer failed: {error ?? "unknown error"}
        <button type="button" onClick={onReset} className="chip rationale-dismiss">Dismiss</button>
      </div>
    );
  }

  return rationale ? <DeckRationaleView rationale={rationale} sideboard={sideboard} /> : null;
}
