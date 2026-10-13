"use client";

import { useEffect, useMemo, useState } from "react";

import { panelId, tabId, Tabs } from "./tabs";
import { bracketLabel } from "@/lib/briefs";
import type { BracketAssessment, DeckResponse, GamePlan, MatchupOutlook } from "@/lib/types";

type TabKey = "why" | "plan" | "sideboard" | "matchups" | "bracket";

const OUTLOOK_LABEL: Record<MatchupOutlook, string> = {
  favored: "Favored",
  even: "Even",
  unfavored: "Unfavored",
  unknown: "Unclear"
};

function hasPlan(plan: GamePlan | undefined): plan is GamePlan {
  if (!plan) return false;
  return Boolean(
    plan.summary ||
      plan.win_conditions.length ||
      plan.opening_hand.length ||
      plan.mulligan.length ||
      Object.values(plan.commander_packages ?? {}).some((cards) => cards.length)
  );
}

function BulletList({ items }: { items: string[] }) {
  return (
    <ul className="plain-bullets">
      {items.map((item, index) => (
        <li key={`${index}-${item}`}>{item}</li>
      ))}
    </ul>
  );
}

function CardNameList({ names, onOpenCard }: { names: string[]; onOpenCard: (name: string) => void }) {
  return (
    <span className="inline-card-list">
      {names.map((name, index) => (
        <span key={name}>
          <button type="button" className="inline-card" onClick={() => onOpenCard(name)}>{name}</button>
          {index < names.length - 1 ? ", " : ""}
        </span>
      ))}
    </span>
  );
}

function GamePlanBody({ plan, onOpenCard }: { plan: GamePlan; onOpenCard: (name: string) => void }) {
  const packages = Object.entries(plan.commander_packages ?? {}).filter(([, cards]) => cards.length);
  return (
    <div className="explanation-body">
      {plan.summary ? <p>{plan.summary}</p> : null}
      {plan.win_conditions.length ? (
        <>
          <h4 className="explanation-subhead">How it wins</h4>
          <BulletList items={plan.win_conditions} />
        </>
      ) : null}
      {plan.opening_hand.length ? (
        <>
          <h4 className="explanation-subhead">A good opening hand</h4>
          <BulletList items={plan.opening_hand} />
        </>
      ) : null}
      {plan.mulligan.length ? (
        <>
          <h4 className="explanation-subhead">When to mulligan</h4>
          <BulletList items={plan.mulligan} />
        </>
      ) : null}
      {packages.length ? (
        <>
          <h4 className="explanation-subhead">Card packages</h4>
          <ul className="plain-bullets">
            {packages.map(([name, cards]) => (
              <li key={name}>
                <strong className="package-name">{name.replace(/_/g, " ")}</strong> ({cards.length}):{" "}
                <CardNameList names={cards} onOpenCard={onOpenCard} />
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

/** Beginner view of the game plan, shown as its own panel instead of a tab. */
export function HowToPlay({ deck, onOpenCard }: { deck: DeckResponse; onOpenCard: (name: string) => void }) {
  if (!hasPlan(deck.game_plan)) return null;
  return (
    <section className="panel results-card" aria-labelledby="how-to-play-heading">
      <h3 id="how-to-play-heading" className="label">How to play this deck</h3>
      <GamePlanBody plan={deck.game_plan} onOpenCard={onOpenCard} />
    </section>
  );
}

function BracketBody({ bracket, onOpenCard }: { bracket: BracketAssessment; onOpenCard: (name: string) => void }) {
  const evidence: [string, string[]][] = [
    ["Game changers", bracket.game_changers],
    ["Mass land denial", bracket.mass_land_denial],
    ["Extra turns", bracket.extra_turns],
    ["Tutors", bracket.tutors]
  ];
  return (
    <div className="explanation-body">
      <div className="bracket-summary">
        <span className="status-pill">Estimated: {bracketLabel(bracket.estimated)}</span>
        {bracket.target ? (
          <span className={`status-pill ${bracket.estimated > bracket.target ? "bad" : "good"}`}>Target: {bracketLabel(bracket.target)}</span>
        ) : null}
      </div>
      <ul className="card-list">
        {evidence.map(([label, cards]) => (
          <li key={label} className="card-row bracket-row">
            <span>{label}</span>
            {cards.length ? <CardNameList names={cards} onOpenCard={onOpenCard} /> : <span className="muted">None</span>}
          </li>
        ))}
        <li className="card-row bracket-row">
          <span>Two-card combos</span>
          {bracket.two_card_combos.length ? (
            <span>{bracket.two_card_combos.map((combo) => combo.join(" + ")).join("; ")}</span>
          ) : (
            <span className="muted">None</span>
          )}
        </li>
      </ul>
      {bracket.notes.length ? <BulletList items={bracket.notes} /> : null}
      {bracket.game_changers_as_of ? (
        <p className="muted field-help">Game Changers list as of {bracket.game_changers_as_of}.</p>
      ) : null}
    </div>
  );
}

type Props = {
  deck: DeckResponse;
  /** Beginners get the game plan as "How to play this deck" instead of a tab. */
  showGamePlanTab: boolean;
  onOpenCard: (name: string) => void;
};

/** Why / Game plan / Sideboard guide / Matchups / Bracket. Empty tabs are hidden. */
export function DeckExplanationTabs({ deck, showGamePlanTab, onOpenCard }: Props) {
  const plan = deck.game_plan;
  const sideboardGuide = plan?.sideboard_guide ?? [];
  const matchups = plan?.matchups ?? [];

  const tabs = useMemo(() => {
    const list: { id: TabKey; label: string }[] = [];
    if (deck.explanation.length || deck.sections.length || deck.mechanics.length) list.push({ id: "why", label: "Why this deck" });
    if (showGamePlanTab && hasPlan(plan)) list.push({ id: "plan", label: "Game plan" });
    if (sideboardGuide.length) list.push({ id: "sideboard", label: "Sideboard guide" });
    if (matchups.length) list.push({ id: "matchups", label: "Matchups" });
    if (deck.bracket) list.push({ id: "bracket", label: "Bracket" });
    return list;
  }, [deck, plan, showGamePlanTab, sideboardGuide.length, matchups.length]);

  const [selected, setSelected] = useState<TabKey>("why");
  useEffect(() => {
    if (tabs.length && !tabs.some((tab) => tab.id === selected)) setSelected(tabs[0].id);
  }, [tabs, selected]);

  if (!tabs.length) return null;
  const active = tabs.some((tab) => tab.id === selected) ? selected : tabs[0].id;
  const prefix = "deck-explain";

  return (
    <section className="panel results-card" aria-label="Deck explanation">
      <Tabs items={tabs} selected={active} onSelect={setSelected} label="Deck explanation" idPrefix={prefix} className="chips explanation-tabs" />
      <div id={panelId(prefix, active)} role="tabpanel" aria-labelledby={tabId(prefix, active)} tabIndex={0} className="explanation-panel">
        {active === "why" ? (
          <div className="explanation-body">
            {deck.explanation.length ? <BulletList items={deck.explanation} /> : null}
            {deck.sections.map((section) => (
              <div key={section.title}>
                <h4 className="explanation-subhead">{section.title}</h4>
                <p className="muted">{section.summary}</p>
                {section.bullets.length ? <BulletList items={section.bullets} /> : null}
              </div>
            ))}
            {deck.mechanics.length ? (
              <>
                <h4 className="explanation-subhead">Key mechanics</h4>
                <ul className="plain-bullets">
                  {deck.mechanics.map((mechanic) => (
                    <li key={mechanic.label}>
                      <strong>{mechanic.label}</strong>: {mechanic.summary}
                      {mechanic.cards.length ? (
                        <>
                          {" "}
                          (<CardNameList names={mechanic.cards} onOpenCard={onOpenCard} />)
                        </>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
        ) : null}
        {active === "plan" && hasPlan(plan) ? <GamePlanBody plan={plan} onOpenCard={onOpenCard} /> : null}
        {active === "sideboard" ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Card</th>
                  <th scope="col">Purpose</th>
                  <th scope="col">Bring in against</th>
                  <th scope="col">Take out</th>
                </tr>
              </thead>
              <tbody>
                {sideboardGuide.map((entry) => (
                  <tr key={entry.card}>
                    <th scope="row">
                      <button type="button" className="inline-card" onClick={() => onOpenCard(entry.card)}>
                        {entry.quantity}x {entry.card}
                      </button>
                    </th>
                    <td>{entry.purpose}</td>
                    <td>{entry.bring_in_against.join(", ") || "—"}</td>
                    <td>{entry.take_out.join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {active === "matchups" ? (
          <ul className="card-list">
            {matchups.map((matchup) => (
              <li key={matchup.opponent} className="card-row matchup-row">
                <div className="matchup-head">
                  <strong>{matchup.opponent}</strong>
                  <span className={`status-pill ${matchup.outlook === "favored" ? "good" : matchup.outlook === "unfavored" ? "bad" : ""}`}>
                    {OUTLOOK_LABEL[matchup.outlook]}
                  </span>
                </div>
                <p className="muted">{matchup.note}</p>
              </li>
            ))}
          </ul>
        ) : null}
        {active === "bracket" && deck.bracket ? <BracketBody bracket={deck.bracket} onOpenCard={onOpenCard} /> : null}
      </div>
    </section>
  );
}
