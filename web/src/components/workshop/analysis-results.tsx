"use client";

import { GroupedDeckList } from "./deck-results";
import { ProvenanceBanner } from "./provenance-banner";
import type { CardRef, DeckAnalysisResponse, FormatName } from "@/lib/types";

type Props = {
  analysis: DeckAnalysisResponse;
  format: FormatName;
  manualMainboard: CardRef[];
  manualSideboard: CardRef[];
  manualCommander: string;
  onOpenCard: (name: string) => void;
};

function DeckCardRow({ card, suffix, quantityLabel, onOpen }: { card: CardRef; suffix: string; quantityLabel: string; onOpen: (name: string) => void }) {
  return (
    <li key={`${card.name}-${suffix}`} className="card-row card-row-action">
      <button type="button" className="card-button" onClick={() => onOpen(card.name)}>
        <span>{card.name}</span>
        <span className="muted">{quantityLabel}</span>
      </button>
    </li>
  );
}

export function AnalysisResults({ analysis, format, manualMainboard, manualSideboard, manualCommander, onOpenCard }: Props) {
  return (
    <>
      <ProvenanceBanner provenance={analysis.provenance} commanderRequested={Boolean(analysis.commander)} />

      <div className="panel results-card">
        <div className="label">What This Deck Is Doing</div>
        <p>{analysis.game_plan_summary}</p>
        <p className="muted" style={{ marginTop: 12 }}>{analysis.play_pattern_summary}</p>
      </div>

      {analysis.ai_coaching_note ? (
        <div className="panel results-card panel-strong">
          <div className="label">
            Claude&apos;s Top Coaching Tips
            {analysis.deep_analysis_used ? <span className="status-pill" style={{ marginLeft: 8 }}>LLM</span> : null}
          </div>
          <div style={{ whiteSpace: "pre-line", lineHeight: 1.7 }}>{analysis.ai_coaching_note}</div>
        </div>
      ) : null}

      <div className="panel results-card">
        <div className="label">Style / Archetype</div>
        <ul className="card-list">
          <li className="card-row">
            <span>Style</span>
            <span className="muted">{analysis.inferred_style}</span>
          </li>
          <li className="card-row">
            <span>Closest Shell</span>
            <span className="muted">{analysis.inferred_archetype}</span>
          </li>
          <li className="card-row" style={{ display: "block" }}>
            <span>{analysis.similarity_label}</span>
          </li>
        </ul>
        {analysis.nearest_archetypes.length ? (
          <p className="muted" style={{ marginTop: 12 }}>
            Nearby archetypes: {analysis.nearest_archetypes.join(", ")}
          </p>
        ) : null}
      </div>

      <div className="panel results-card">
        <div className="deck-columns">
          <div>
            <div className="label">
              Mainboard
              <span className="muted" style={{ marginLeft: 8, fontWeight: "normal" }}>
                {manualMainboard.reduce((sum, ref) => sum + ref.quantity, 0)} cards
              </span>
            </div>
            <GroupedDeckList cards={manualMainboard} typeMap={analysis.card_types} suffix="manual-main" onOpenCard={onOpenCard} />
          </div>
          <div>
            <div className="label">{format === "commander" ? "Commander / Sideboard" : "Sideboard"}</div>
            {format === "commander" && manualCommander ? (
              <ul className="card-list" style={{ marginBottom: 12 }}>
                <DeckCardRow card={{ name: manualCommander, quantity: 1 }} suffix="manual-commander" quantityLabel="Commander" onOpen={onOpenCard} />
              </ul>
            ) : null}
            {manualSideboard.length ? (
              <GroupedDeckList cards={manualSideboard} typeMap={analysis.card_types} suffix="manual-side" onOpenCard={onOpenCard} />
            ) : format !== "commander" ? (
              <p className="muted">No sideboard cards submitted.</p>
            ) : null}
          </div>
        </div>
      </div>

      <div className="panel results-card">
        <div className="label">Strengths</div>
        <ul className="card-list">
          {analysis.strengths.map((item, index) => (
            <li key={`strength-${index}`} className="card-row"><span>{item}</span></li>
          ))}
        </ul>
      </div>

      <div className="panel results-card">
        <div className="label">Weaknesses</div>
        <ul className="card-list">
          {analysis.weaknesses.map((item, index) => (
            <li key={`weakness-${index}`} className="card-row"><span>{item}</span></li>
          ))}
        </ul>
      </div>

      <div className="panel results-card">
        <div className="label">Suggested Improvements</div>
        <div className="card-list">
          {analysis.advice.keep_doing.length ? <div className="card-row" style={{ display: "block" }}><strong>Keep Doing</strong><p className="muted">{analysis.advice.keep_doing.join(" ")}</p></div> : null}
          {analysis.advice.watch_out_for.length ? <div className="card-row" style={{ display: "block" }}><strong>Watch Out For</strong><p className="muted">{analysis.advice.watch_out_for.join(" ")}</p></div> : null}
          {analysis.advice.add_more_of.length ? <div className="card-row" style={{ display: "block" }}><strong>Add More Of</strong><p className="muted">{analysis.advice.add_more_of.join(" ")}</p></div> : null}
          {analysis.advice.cut_some_of.length ? <div className="card-row" style={{ display: "block" }}><strong>Cut Some Of</strong><p className="muted">{analysis.advice.cut_some_of.join(" ")}</p></div> : null}
          {analysis.advice.possible_upgrades.length ? <div className="card-row" style={{ display: "block" }}><strong>Possible Upgrades</strong><p className="muted">{analysis.advice.possible_upgrades.join(" ")}</p></div> : null}
        </div>
      </div>

      {analysis.improvement_suggestions.length ? (
        <div className="panel results-card">
          <div className="label">Upgrade Packages</div>
          <ul className="card-list">
            {analysis.improvement_suggestions.map((item) => (
              <li key={item.category} className="card-row" style={{ display: "block" }}>
                <strong>{item.category}</strong>
                <p className="muted" style={{ marginTop: 6 }}>{item.summary}</p>
                {item.candidate_cards.length ? (
                  <div className="chips" style={{ marginTop: 8 }}>
                    {item.candidate_cards.map((cardName) => (
                      <button key={`${item.category}-${cardName}`} type="button" className="chip" onClick={() => onOpenCard(cardName)}>
                        {cardName}
                      </button>
                    ))}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {analysis.swap_recommendations.length ? (
        <div className="panel results-card panel-strong">
          <div className="label">Exact Add / Cut Ideas</div>
          <ul className="card-list">
            {analysis.swap_recommendations.map((item, index) => (
              <li key={`${item.category}-${item.cut_card}-${item.add_card}-${index}`} className="card-row" style={{ display: "block" }}>
                <strong>{item.category}</strong>
                <div className="chips" style={{ marginTop: 8 }}>
                  <button type="button" className="chip" onClick={() => onOpenCard(item.cut_card)}>Cut {item.cut_card}</button>
                  <button type="button" className="chip" onClick={() => onOpenCard(item.add_card)}>Add {item.add_card}</button>
                </div>
                <p className="muted" style={{ marginTop: 8 }}>{item.reason}</p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {analysis.nearest_shell_comparison ? (
        <div className="panel results-card">
          <div className="label">Nearest Shell Comparison</div>
          <p className="muted">
            {analysis.nearest_shell_comparison.shell_name} • confidence {Math.round(analysis.nearest_shell_comparison.confidence * 100)}%
          </p>
          <div className="deck-columns">
            <div>
              <div className="label">Shared Cards</div>
              <ul className="card-list">
                {analysis.nearest_shell_comparison.overlap_cards.map((cardName) => (
                  <li key={`overlap-${cardName}`} className="card-row">
                    <button type="button" className="card-button" onClick={() => onOpenCard(cardName)}>{cardName}</button>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="label">Missing From Shell</div>
              <ul className="card-list">
                {analysis.nearest_shell_comparison.missing_cards.map((cardName) => (
                  <li key={`missing-${cardName}`} className="card-row">
                    <button type="button" className="card-button" onClick={() => onOpenCard(cardName)}>{cardName}</button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          {analysis.nearest_shell_comparison.off_plan_cards.length ? (
            <>
              <div className="label" style={{ marginTop: 16 }}>Possible Off-Plan Cards</div>
              <div className="chips" style={{ marginTop: 8 }}>
                {analysis.nearest_shell_comparison.off_plan_cards.map((cardName) => (
                  <button key={`offplan-${cardName}`} type="button" className="chip" onClick={() => onOpenCard(cardName)}>
                    {cardName}
                  </button>
                ))}
              </div>
            </>
          ) : null}
        </div>
      ) : null}

      {(analysis.role_summary.length || analysis.mana_curve.length) ? (
        <div className="panel results-card">
          <div className="label">Validation / Mana / Roles</div>
          <div className="deck-columns">
            <div>
              <div className="label">Roles</div>
              <ul className="card-list">
                {analysis.role_summary.map((item) => (
                  <li key={item.role} className="card-row">
                    <span>{item.role}</span>
                    <span className="muted">{item.total_cards}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="label">Mana Curve</div>
              <ul className="card-list">
                {analysis.mana_curve.map((point) => (
                  <li key={point.mana_value} className="card-row">
                    <span>{point.mana_value === 6 ? "6+" : point.mana_value}</span>
                    <span className="muted">{point.card_count}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      ) : null}

      {analysis.synergy_observations.length ? (
        <div className="panel results-card">
          <div className="label">Synergy Notes</div>
          <ul className="card-list">
            {analysis.synergy_observations.map((item, index) => (
              <li key={`synergy-${index}`} className="card-row"><span>{item}</span></li>
            ))}
          </ul>
        </div>
      ) : null}

      {analysis.validation.warnings.length ? (
        <div className="panel results-card">
          <div className="label">Quality Warnings</div>
          <p className="muted" style={{ marginTop: 0 }}>These do not block play but are worth tightening.</p>
          <ul className="card-list">
            {analysis.validation.warnings.map((item, index) => (
              <li key={`val-warning-${index}`} className="card-row"><span>{item}</span></li>
            ))}
          </ul>
        </div>
      ) : null}

      {analysis.validation.errors.length ? (
        <div className="panel results-card panel-error">
          <div className="label">Blocking Legality Errors</div>
          <ul className="card-list">
            {analysis.validation.errors.map((item, index) => (
              <li key={`analysis-error-${index}`} className="card-row"><span>{item}</span></li>
            ))}
          </ul>
        </div>
      ) : null}
    </>
  );
}
