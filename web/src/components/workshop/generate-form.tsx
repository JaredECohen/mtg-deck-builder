"use client";

type Props = {
  expertMode: boolean;
  onExpertModeChange: (value: boolean) => void;
  budget: string;
  onBudgetChange: (value: string) => void;
  prompt: string;
  onPromptChange: (value: string) => void;
  onSubmit: () => void;
  loading: boolean;
};

export function GenerateForm({
  expertMode,
  onExpertModeChange,
  budget,
  onBudgetChange,
  prompt,
  onPromptChange,
  onSubmit,
  loading
}: Props) {
  return (
    <>
      <div className="panel form-card" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: "0.9rem" }}>
          <input
            type="checkbox"
            checked={expertMode}
            onChange={(event) => onExpertModeChange(event.target.checked)}
            style={{ accentColor: "var(--accent, #6366f1)", width: 16, height: 16 }}
          />
          Expert mode
        </label>
        <span className="muted" style={{ fontSize: "0.8rem", marginLeft: 24 }}>
          Adds a Budget (USD) cap to the build. Off = no spend limit.
        </span>
      </div>

      {expertMode ? (
        <div className="panel form-card">
          <label className="label" htmlFor="budget">Budget (USD)</label>
          <input id="budget" className="input" value={budget} onChange={(event) => onBudgetChange(event.target.value)} placeholder="e.g. 100" />
        </div>
      ) : null}

      <div className="panel form-card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <label className="label" htmlFor="prompt">Build Brief</label>
          <span style={{ fontSize: "0.75rem", color: prompt.length > 1200 ? "orange" : "#9ca3af" }}>{prompt.length}/1500</span>
        </div>
        <textarea
          id="prompt"
          className="textarea"
          value={prompt}
          maxLength={1500}
          onChange={(event) => onPromptChange(event.target.value)}
          placeholder="Describe the deck you want. e.g. 'Modern burn, mono-red, aggressive damage to face' or 'Standard control with planeswalker finishers'."
        />
      </div>

      <button type="button" className="button" onClick={onSubmit} disabled={loading}>
        {loading ? "Forging deck..." : "Build My Deck"}
      </button>
    </>
  );
}
