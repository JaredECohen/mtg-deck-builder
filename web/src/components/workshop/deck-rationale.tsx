"use client";

/**
 * DeckRationaleView: the optimizer's structured "why this deck wins" payload
 * (headline, kill turn / win rate, win plan, key turns, mulligan guide,
 * matchups, weaknesses, critic transcript, sideboard plan).
 */

import type { ReactNode } from "react";

import type { DeckRationaleData, SideboardPlanData } from "@/lib/types";

type Props = {
  rationale: DeckRationaleData;
  sideboard?: SideboardPlanData | null;
};

function formatPct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function DeckRationaleView({ rationale, sideboard }: Props) {
  const winRate = rationale.win_rate ? formatPct(rationale.win_rate) : "—";
  const killTurn = rationale.avg_kill_turn ? rationale.avg_kill_turn.toFixed(1) : "—";

  return (
    <section className="panel results-card rationale" aria-labelledby="rationale-headline">
      <header className="rationale-header">
        <div>
          <div className="label">Simulator rationale</div>
          <h3 id="rationale-headline" className="rationale-headline">{rationale.headline}</h3>
          <p className="muted rationale-archetype">{rationale.archetype}</p>
        </div>
        <div className="rationale-stats">
          <Stat label="Avg kill turn" value={killTurn} />
          <Stat label="Goldfish win rate" value={winRate} />
        </div>
      </header>

      {rationale.why_this_wins.length > 0 && (
        <Block title="Why this deck wins">
          <ul className="plain-bullets">
            {rationale.why_this_wins.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </Block>
      )}

      {rationale.key_turns.length > 0 && (
        <Block title="Key turns">
          <ol className="key-turns">
            {rationale.key_turns.map((t) => (
              <li key={t.turn}>
                <span className="key-turn-label">T{t.turn}</span>
                <span>{t.description}</span>
              </li>
            ))}
          </ol>
        </Block>
      )}

      {rationale.mulligan_guide.keep_threshold_summary && (
        <Block title="Mulligan guide">
          <p>{rationale.mulligan_guide.keep_threshold_summary}</p>
          {rationale.mulligan_guide.keep_examples.length > 0 && (
            <p>
              <span className="text-good">Keep:</span> {rationale.mulligan_guide.keep_examples.join(" · ")}
            </p>
          )}
          {rationale.mulligan_guide.mulligan_examples.length > 0 && (
            <p>
              <span className="text-bad">Mulligan:</span> {rationale.mulligan_guide.mulligan_examples.join(" · ")}
            </p>
          )}
        </Block>
      )}

      {rationale.soft_matchups.length > 0 && (
        <Block title="Matchups">
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Opponent</th>
                  <th scope="col" className="num">Win %</th>
                  <th scope="col">Plan</th>
                </tr>
              </thead>
              <tbody>
                {rationale.soft_matchups.map((m) => (
                  <tr key={m.opponent_archetype}>
                    <th scope="row">{m.opponent_archetype}</th>
                    <td className="num">{formatPct(m.win_rate)}</td>
                    <td>{m.plan}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Block>
      )}

      {rationale.weakness_callouts.length > 0 && (
        <Block title="Soft spots">
          <ul className="plain-bullets text-warn">
            {rationale.weakness_callouts.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </Block>
      )}

      {rationale.critic_transcript.length > 0 && (
        <Block title="Critic transcript">
          <ul className="critic-rounds">
            {rationale.critic_transcript.map((r) => (
              <li key={r.round}>
                <div className="muted">Round {r.round + 1}</div>
                {r.flagged.length > 0 && (
                  <div>
                    <span className="text-warn">Flagged:</span> {r.flagged.join("; ")}
                  </div>
                )}
                {r.fixed.length > 0 && (
                  <div>
                    <span className="text-good">Required fixes:</span> {r.fixed.join("; ")}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Block>
      )}

      {sideboard && sideboard.slots.length > 0 && (
        <Block title={`Sideboard plan (${sideboard.total_cards}/15)`}>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Card</th>
                  <th scope="col">Vs.</th>
                  <th scope="col">Why</th>
                </tr>
              </thead>
              <tbody>
                {sideboard.slots.map((s, i) => (
                  <tr key={`${s.card_name}-${i}`}>
                    <th scope="row">{s.card_name}</th>
                    <td className="muted">{s.matchup_target}</td>
                    <td>{s.rationale}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Block>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rationale-stat">
      <span className="rationale-stat-label">{label}</span>
      <span className="rationale-stat-value">{value}</span>
    </div>
  );
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rationale-block">
      <h4 className="explanation-subhead">{title}</h4>
      {children}
    </div>
  );
}
