"use client";

import { STRATEGY_OPTIONS, toggleValue, type StrategyId } from "@/lib/strategies";

type Props = {
  selected: StrategyId[];
  onChange: (next: StrategyId[]) => void;
};

export function StrategyPicker({ selected, onChange }: Props) {
  return (
    <div className="panel form-card">
      <span className="label">Deck Strategy</span>
      <div className="chips">
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
    </div>
  );
}
