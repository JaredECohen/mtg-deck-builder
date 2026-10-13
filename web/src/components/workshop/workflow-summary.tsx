import type { ReactNode } from "react";

import type { DataStatusResponse, ScoreBreakdown } from "@/lib/types";

type Legality = {
  isLegal: boolean;
  errorCount: number;
  warningCount: number;
};

type Props = {
  title: string;
  summary: string;
  dataStatus: DataStatusResponse | null;
  error: string | null;
  score?: ScoreBreakdown;
  price?: number | null;
  health?: { value: string; explanation: string };
  legality?: Legality;
  /** Extra status shown under the data line (e.g. "built for another format"). */
  badge?: ReactNode;
};

export function WorkflowSummary({ title, summary, dataStatus, error, score, price, health, legality, badge }: Props) {
  return (
    <div className="panel results-card panel-strong">
      <div className="eyebrow">Deck Workshop</div>
      <h2 className="workshop-result-title">{title}</h2>
      <p className="muted">{summary}</p>
      {dataStatus ? (
        <p className="muted workshop-data-status">
          Card data: {dataStatus.card_source} ({dataStatus.card_count.toLocaleString()} cards
          {dataStatus.card_data_as_of ? `, through ${dataStatus.card_data_as_of}` : ""})
          {" • "}
          Archetypes: {dataStatus.archetype_source} ({dataStatus.archetype_count})
          {dataStatus.stale ? (
            <span className="data-stale" title="Newer sets, prices and ban-list changes may be missing until the card data is refreshed.">
              {" • "}Card data may be out of date
            </span>
          ) : null}
        </p>
      ) : null}
      {badge ? <div className="summary-badge">{badge}</div> : null}
      {error ? <p className="workflow-error" role="alert">{error}</p> : null}
      {score ? <ResultStats score={score} price={price} health={health} /> : null}
      {legality ? <LegalityBanner {...legality} /> : null}
    </div>
  );
}

function ResultStats({
  score,
  price,
  health
}: {
  score: ScoreBreakdown;
  price?: number | null;
  health?: { value: string; explanation: string };
}) {
  return (
    <div className="stats stats-four workshop-stats">
      <div className="stat">
        <span className="muted">Quality score</span>
        <strong>{score.total}</strong>
      </div>
      {health ? (
        <div className="stat">
          <span className="muted">Deck health</span>
          <strong className="health-label">{health.value}</strong>
          {health.explanation ? <p className="health-explanation">{health.explanation}</p> : null}
        </div>
      ) : (
        <div className="stat">
          <span className="muted">Mana</span>
          <strong>{score.mana}</strong>
        </div>
      )}
      <div className="stat">
        <span className="muted">Synergy</span>
        <strong>{score.synergy}</strong>
      </div>
      <div className="stat">
        <span className="muted">{price !== undefined ? "Est. price" : "Curve"}</span>
        <strong>{price !== undefined && price !== null ? `$${price.toFixed(0)}` : score.curve}</strong>
      </div>
    </div>
  );
}

function LegalityBanner({ isLegal, errorCount, warningCount }: Legality) {
  return (
    <div className="validation-banner workshop-legality">
      <span className={`status-pill ${isLegal ? "good" : "bad"}`}>{isLegal ? "Legal" : "Blocked"}</span>
      {errorCount ? (
        <span className="status-pill bad">{errorCount} blocking issue{errorCount === 1 ? "" : "s"}</span>
      ) : warningCount ? (
        <span className="muted">{warningCount} non-blocking quality warning{warningCount === 1 ? "" : "s"}</span>
      ) : (
        <span className="muted">No validation issues</span>
      )}
    </div>
  );
}
