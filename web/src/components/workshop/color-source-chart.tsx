"use client";

import type { ColorSourcePoint } from "@/lib/types";

const COLOR_NAMES: Record<string, string> = {
  W: "White",
  U: "Blue",
  B: "Black",
  R: "Red",
  G: "Green",
  C: "Colorless"
};

/**
 * Per color: mana sources in the deck vs. mana symbols (pips) its spells ask
 * for. Bars are decorative; the visually hidden table is the accessible version.
 */
export function ColorSourceChart({ points }: { points: ColorSourcePoint[] }) {
  const rows = points.filter((point) => point.sources > 0 || point.pips > 0);
  if (!rows.length) return null;
  const peak = Math.max(1, ...rows.flatMap((point) => [point.sources, point.pips]));

  return (
    <figure className="chart" aria-labelledby="color-source-caption">
      <figcaption id="color-source-caption" className="label">Color sources vs. pips</figcaption>
      <div className="source-legend" aria-hidden="true">
        <span><span className="legend-swatch sources" /> Sources</span>
        <span><span className="legend-swatch pips" /> Pips</span>
      </div>
      <div className="source-rows" aria-hidden="true">
        {rows.map((point) => (
          <div key={point.color} className={`source-row mana-${point.color.toLowerCase()}`}>
            <span className="source-color">{COLOR_NAMES[point.color] ?? point.color}</span>
            <div className="source-bars">
              <div className="source-bar sources" style={{ width: `${(point.sources / peak) * 100}%` }} />
              <div className="source-bar pips" style={{ width: `${(point.pips / peak) * 100}%` }} />
            </div>
            <span className="source-values">
              {point.sources} / {point.pips}
            </span>
          </div>
        ))}
      </div>
      <table className="sr-only">
        <caption>Mana sources and mana symbols per color</caption>
        <thead>
          <tr>
            <th scope="col">Color</th>
            <th scope="col">Sources</th>
            <th scope="col">Pips</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((point) => (
            <tr key={point.color}>
              <th scope="row">{COLOR_NAMES[point.color] ?? point.color}</th>
              <td>{point.sources}</td>
              <td>{point.pips}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
