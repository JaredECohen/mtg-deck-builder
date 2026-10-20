"use client";

import { useId } from "react";

import { CardListInput } from "./card-list-input";
import { MAX_CARD_NAMES } from "@/lib/api";
import { BRACKET_OPTIONS, MODE_OPTIONS, parseCardNameLines } from "@/lib/briefs";
import type { FormatName, GenerationMode, MatchType } from "@/lib/types";

export type ExpertSettings = {
  budget: string;
  mode: GenerationMode;
  matchType: MatchType;
  /** Commander only. null = no target. */
  bracket: number | null;
  includeCards: string[];
  excludeCards: string[];
  /** One card name per line. */
  ownedText: string;
};

export const DEFAULT_EXPERT_SETTINGS: ExpertSettings = {
  budget: "",
  mode: "constraint-aware",
  matchType: "bo3",
  bracket: null,
  includeCards: [],
  excludeCards: [],
  ownedText: ""
};

type Props = {
  format: FormatName | null;
  settings: ExpertSettings;
  onChange: (next: ExpertSettings) => void;
};

export function ExpertControls({ format, settings, onChange }: Props) {
  const id = useId();
  const isCommander = format === "commander";
  const ownedCount = parseCardNameLines(settings.ownedText).length;
  const modeHelp = MODE_OPTIONS.find((option) => option.value === settings.mode)?.description;
  const bracketHelp = BRACKET_OPTIONS.find((option) => option.value === settings.bracket)?.description;

  function patch(update: Partial<ExpertSettings>) {
    onChange({ ...settings, ...update });
  }

  return (
    <div className="panel form-card expert-controls">
      <div className="label">Expert controls</div>

      <div className="expert-grid">
        <div>
          <label className="label" htmlFor={`${id}-budget`}>Budget (USD)</label>
          <input
            id={`${id}-budget`}
            className="input"
            inputMode="decimal"
            value={settings.budget}
            onChange={(event) => patch({ budget: event.target.value })}
            placeholder="No limit"
          />
        </div>
        <div>
          <label className="label" htmlFor={`${id}-mode`}>Build mode</label>
          <select
            id={`${id}-mode`}
            className="select"
            value={settings.mode}
            aria-describedby={`${id}-mode-help`}
            onChange={(event) => patch({ mode: event.target.value as GenerationMode })}
          >
            {MODE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </div>
      </div>
      <p id={`${id}-mode-help`} className="muted field-help">{modeHelp}</p>

      {isCommander ? (
        <div className="expert-field">
          <label className="label" htmlFor={`${id}-bracket`}>Power bracket</label>
          <select
            id={`${id}-bracket`}
            className="select"
            value={settings.bracket ?? ""}
            aria-describedby={`${id}-bracket-help`}
            onChange={(event) => patch({ bracket: event.target.value ? Number(event.target.value) : null })}
          >
            <option value="">Any power level</option>
            {BRACKET_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <p id={`${id}-bracket-help`} className="muted field-help">
            {bracketHelp ?? "Pick a bracket to keep the deck at your table's power level."}
          </p>
        </div>
      ) : (
        <fieldset className="expert-field plain-fieldset">
          <legend className="label">Match type</legend>
          <div className="chips">
            {(["bo3", "bo1"] as const).map((value) => (
              <button
                key={value}
                type="button"
                className={`chip ${settings.matchType === value ? "active" : ""}`}
                aria-pressed={settings.matchType === value}
                onClick={() => patch({ matchType: value })}
              >
                {value === "bo3" ? "Best-of-three (with sideboard)" : "Best-of-one (no sideboard)"}
              </button>
            ))}
          </div>
        </fieldset>
      )}

      <div className="expert-field">
        <CardListInput
          label="Must include"
          help="Cards the deck should play. Ones that can't fit are listed with the reason."
          format={format}
          values={settings.includeCards}
          onChange={(includeCards) => patch({ includeCards })}
          listNoun="include"
        />
      </div>
      <div className="expert-field">
        <CardListInput
          label="Never include"
          format={format}
          values={settings.excludeCards}
          onChange={(excludeCards) => patch({ excludeCards })}
          listNoun="exclude"
        />
      </div>

      <div className="expert-field">
        <div className="field-label-row">
          <label className="label" htmlFor={`${id}-owned`}>Cards I own</label>
          <span className={`muted field-count ${ownedCount > MAX_CARD_NAMES ? "over" : ""}`}>
            {ownedCount}/{MAX_CARD_NAMES}
          </span>
        </div>
        <textarea
          id={`${id}-owned`}
          className="textarea textarea-compact"
          value={settings.ownedText}
          aria-describedby={`${id}-owned-help`}
          onChange={(event) => patch({ ownedText: event.target.value })}
          placeholder={"Lightning Bolt\nRagavan, Nimble Pilferer"}
        />
        <p id={`${id}-owned-help`} className="muted field-help">
          One card per line. Owned cards are preferred and don&apos;t count toward the budget.
          {ownedCount > MAX_CARD_NAMES ? ` Only the first ${MAX_CARD_NAMES} are sent.` : ""}
        </p>
      </div>
    </div>
  );
}
