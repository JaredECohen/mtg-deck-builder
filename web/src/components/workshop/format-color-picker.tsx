"use client";

import { COLORS, toggleValue } from "@/lib/strategies";
import type { FormatName } from "@/lib/types";

type Props = {
  format: FormatName;
  colors: string[];
  onFormatChange: (format: FormatName) => void;
  onColorsChange: (colors: string[]) => void;
};

export function FormatColorPicker({ format, colors, onFormatChange, onColorsChange }: Props) {
  return (
    <>
      <div className="panel form-card panel-strong">
        <label className="label" htmlFor="format">Format</label>
        <select id="format" className="select" value={format} onChange={(event) => onFormatChange(event.target.value as FormatName)}>
          <option value="standard">Standard</option>
          <option value="modern">Modern</option>
          <option value="legacy">Legacy</option>
          <option value="commander">Commander</option>
        </select>
      </div>
      <div className="panel form-card">
        <span className="label">Colors</span>
        <div className="chips">
          {COLORS.map((color) => (
            <button
              key={color}
              type="button"
              className={`chip ${colors.includes(color) ? "active" : ""}`}
              onClick={() => onColorsChange(toggleValue(color, colors))}
              aria-pressed={colors.includes(color)}
            >
              {color}
            </button>
          ))}
        </div>
      </div>
    </>
  );
}
