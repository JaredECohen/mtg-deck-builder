"use client";

import { useId } from "react";

import { COLORS, toggleValue } from "@/lib/strategies";
import type { FormatName } from "@/lib/types";

type Props = {
  format: FormatName;
  colors: string[];
  onFormatChange: (format: FormatName) => void;
  onColorsChange: (colors: string[]) => void;
  showColors?: boolean;
};

export function FormatColorPicker({ format, colors, onFormatChange, onColorsChange, showColors = true }: Props) {
  // Rendered by both the Generate and Analyze workflows (both stay mounted),
  // so a fixed id would be duplicated on the page.
  const formatId = useId();
  return (
    <>
      <div className="panel form-card panel-strong">
        <label className="label" htmlFor={formatId}>Format</label>
        <select id={formatId} className="select" value={format} onChange={(event) => onFormatChange(event.target.value as FormatName)}>
          <option value="standard">Standard</option>
          <option value="modern">Modern</option>
          <option value="pioneer">Pioneer</option>
          <option value="legacy">Legacy</option>
          <option value="commander">Commander</option>
        </select>
      </div>
      {showColors ? (
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
      ) : null}
    </>
  );
}
