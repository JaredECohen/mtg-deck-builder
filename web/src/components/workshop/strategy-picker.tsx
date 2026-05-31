"use client";

import { STRATEGY_OPTIONS, toggleValue, type StrategyId } from "@/lib/strategies";

type Props = {
  selected: StrategyId[];
  onChange: (next: StrategyId[]) => void;
};

export function StrategyPicker({ selected, onChange }: Props) {
  const selectedLabels = STRATEGY_OPTIONS.filter((option) => selected.includes(option.id)).map((option) => option.label);
  const summaryText = selectedLabels.length === 0 ? "Any" : selectedLabels.join(", ");

  return (
    <details className="panel form-card strategy-picker">
      <summary className="strategy-summary">
        <span className="label">Deck Strategy</span>
        <span className="strategy-summary-value">{summaryText}</span>
      </summary>
      <div className="chips" style={{ marginTop: 12 }}>
        {STRATEGY_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            className={`chip chip-rich ${selected.includes(option.id) ? "active" : ""}`}
            onClick={() => onChange(toggleValue(option.id, selected) as StrategyId[])}
            aria-pressed={selected.includes(option.id)}
          >
            <strong>{option.label}</strong>
            <span>{option.description}</span>
          </button>
        ))}
      </div>
    </details>
  );
}
