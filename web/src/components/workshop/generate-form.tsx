"use client";

import { ExpertControls, type ExpertSettings } from "./expert-controls";
import { MAX_PROMPT_CHARS } from "@/lib/api";
import { EXAMPLE_BRIEFS } from "@/lib/briefs";
import type { FormatName } from "@/lib/types";

type Props = {
  format: FormatName | null;
  expertMode: boolean;
  onExpertModeChange: (value: boolean) => void;
  expertSettings: ExpertSettings;
  onExpertSettingsChange: (value: ExpertSettings) => void;
  prompt: string;
  /** `edited` is true when the user typed it (vs. picking an example). */
  onPromptChange: (value: string, edited: boolean) => void;
  onSubmit: () => void;
  loading: boolean;
};

export function GenerateForm({
  format,
  expertMode,
  onExpertModeChange,
  expertSettings,
  onExpertSettingsChange,
  prompt,
  onPromptChange,
  onSubmit,
  loading
}: Props) {
  return (
    <>
      <div className="panel form-card expert-toggle">
        <label className="checkbox-label">
          <input type="checkbox" checked={expertMode} onChange={(event) => onExpertModeChange(event.target.checked)} />
          Expert mode
        </label>
        <span className="muted field-help expert-toggle-help">
          Adds a budget, must-include and never-include cards, cards you own, build mode,
          {format === "commander" ? " and a power bracket." : " and best-of-one or best-of-three."}
        </span>
      </div>

      {expertMode ? <ExpertControls format={format} settings={expertSettings} onChange={onExpertSettingsChange} /> : null}

      <div className="panel form-card">
        <div className="field-label-row">
          <label className="label" htmlFor="prompt">Build Brief</label>
          <span className={`muted field-count ${prompt.length > MAX_PROMPT_CHARS * 0.8 ? "warn" : ""}`}>
            {prompt.length}/{MAX_PROMPT_CHARS}
          </span>
        </div>
        <textarea
          id="prompt"
          className="textarea"
          value={prompt}
          maxLength={MAX_PROMPT_CHARS}
          onChange={(event) => onPromptChange(event.target.value, true)}
          placeholder="Describe the deck you want. e.g. 'Modern burn, mono-red, aggressive damage to face' or 'Standard control with planeswalker finishers'."
        />
        {format ? (
        <div className="example-briefs">
          <span className="muted field-help" id="example-briefs-label">Try an example:</span>
          <ul className="chips" aria-labelledby="example-briefs-label">
            {EXAMPLE_BRIEFS[format].map((example) => (
              <li key={example}>
                <button
                  type="button"
                  className={`chip chip-small ${prompt === example ? "active" : ""}`}
                  aria-pressed={prompt === example}
                  onClick={() => onPromptChange(example, false)}
                >
                  {example}
                </button>
              </li>
            ))}
          </ul>
        </div>
        ) : null}
      </div>

      <button type="button" className="button" onClick={onSubmit} disabled={loading}>
        {loading ? "Forging deck..." : "Build My Deck"}
      </button>
    </>
  );
}
