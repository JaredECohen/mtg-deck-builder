"use client";

/**
 * DeckRationale — renders the Phase 8 structured "why this deck wins"
 * payload returned alongside every optimized deck.
 *
 * Sections:
 *  - Headline + win rate / kill turn
 *  - Why this deck wins (bullets)
 *  - Key turns
 *  - Mulligan guide
 *  - Soft matchups
 *  - Weakness callouts
 *  - Critic transcript (if any)
 */

export type TurnPlan = {
  turn: number;
  description: string;
};

export type MulliganGuide = {
  keep_examples: string[];
  mulligan_examples: string[];
  keep_threshold_summary: string;
};

export type MatchupPlan = {
  opponent_archetype: string;
  win_rate: number;
  plan: string;
  sideboard_in: string[];
  sideboard_out: string[];
};

export type CriticRound = {
  round: number;
  flagged: string[];
  fixed: string[];
};

export type DeckRationaleData = {
  headline: string;
  archetype: string;
  avg_kill_turn: number;
  win_rate: number;
  why_this_wins: string[];
  key_turns: TurnPlan[];
  mulligan_guide: MulliganGuide;
  soft_matchups: MatchupPlan[];
  sideboard_priorities: string[];
  critic_transcript: CriticRound[];
  weakness_callouts: string[];
  fitness_breakdown: Record<string, number>;
  cards_breakdown: Record<string, string[]>;
};

type Props = {
  rationale: DeckRationaleData;
};

function formatPct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function DeckRationaleView({ rationale }: Props) {
  const winRate = rationale.win_rate ? formatPct(rationale.win_rate) : "—";
  const killTurn = rationale.avg_kill_turn ? rationale.avg_kill_turn.toFixed(1) : "—";

  return (
    <section className="rounded-lg border border-zinc-700 bg-zinc-900/40 p-4 space-y-4">
      <header className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold text-zinc-100">{rationale.headline}</h2>
          <p className="text-sm text-zinc-400 capitalize">{rationale.archetype}</p>
        </div>
        <div className="flex gap-4 text-sm">
          <Stat label="Avg kill turn" value={killTurn} />
          <Stat label="Goldfish win rate" value={winRate} />
        </div>
      </header>

      {rationale.why_this_wins.length > 0 && (
        <Block title="Why this deck wins">
          <ul className="list-disc pl-5 space-y-1 text-sm text-zinc-200">
            {rationale.why_this_wins.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </Block>
      )}

      {rationale.key_turns.length > 0 && (
        <Block title="Key turns">
          <ol className="space-y-1 text-sm text-zinc-200">
            {rationale.key_turns.map((t) => (
              <li key={t.turn} className="flex gap-2">
                <span className="font-mono text-zinc-400 shrink-0">T{t.turn}</span>
                <span>{t.description}</span>
              </li>
            ))}
          </ol>
        </Block>
      )}

      {rationale.mulligan_guide.keep_threshold_summary && (
        <Block title="Mulligan guide">
          <p className="text-sm text-zinc-200 mb-2">
            {rationale.mulligan_guide.keep_threshold_summary}
          </p>
          {rationale.mulligan_guide.keep_examples.length > 0 && (
            <p className="text-sm text-zinc-300">
              <span className="text-emerald-400 font-medium">Keep:</span>{" "}
              {rationale.mulligan_guide.keep_examples.join(" · ")}
            </p>
          )}
          {rationale.mulligan_guide.mulligan_examples.length > 0 && (
            <p className="text-sm text-zinc-300">
              <span className="text-rose-400 font-medium">Mulligan:</span>{" "}
              {rationale.mulligan_guide.mulligan_examples.join(" · ")}
            </p>
          )}
        </Block>
      )}

      {rationale.soft_matchups.length > 0 && (
        <Block title="Matchups">
          <table className="w-full text-sm">
            <thead className="text-zinc-400">
              <tr>
                <th className="text-left font-normal">Opponent</th>
                <th className="text-right font-normal">Win %</th>
                <th className="text-left font-normal pl-3">Plan</th>
              </tr>
            </thead>
            <tbody className="text-zinc-200">
              {rationale.soft_matchups.map((m) => (
                <tr key={m.opponent_archetype} className="border-t border-zinc-800">
                  <td className="py-1">{m.opponent_archetype}</td>
                  <td className="py-1 text-right font-mono">{formatPct(m.win_rate)}</td>
                  <td className="py-1 pl-3 text-zinc-300">{m.plan}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Block>
      )}

      {rationale.weakness_callouts.length > 0 && (
        <Block title="Soft spots">
          <ul className="list-disc pl-5 space-y-1 text-sm text-amber-300/90">
            {rationale.weakness_callouts.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </Block>
      )}

      {rationale.critic_transcript.length > 0 && (
        <Block title="Critic transcript">
          <ul className="space-y-2 text-sm">
            {rationale.critic_transcript.map((r) => (
              <li key={r.round} className="border-l-2 border-zinc-700 pl-3">
                <div className="text-zinc-400">Round {r.round + 1}</div>
                {r.flagged.length > 0 && (
                  <div className="text-zinc-200">
                    <span className="text-amber-400">Flagged:</span> {r.flagged.join("; ")}
                  </div>
                )}
                {r.fixed.length > 0 && (
                  <div className="text-zinc-200">
                    <span className="text-emerald-400">Required fixes:</span> {r.fixed.join("; ")}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Block>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-end">
      <span className="text-xs uppercase tracking-wide text-zinc-500">{label}</span>
      <span className="font-mono text-zinc-100">{value}</span>
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-zinc-300 mb-2 uppercase tracking-wide">{title}</h3>
      {children}
    </div>
  );
}
