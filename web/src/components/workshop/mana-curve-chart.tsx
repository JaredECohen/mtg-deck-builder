"use client";

import type { ManaCurvePoint } from "@/lib/types";

/**
 * Bar chart of nonland cards by mana value, from the deck's `mana_curve`
 * (the API buckets 6+ into 6). Div bars, no chart library. The bars are
 * hidden from assistive tech; a visually hidden table carries the numbers.
 */
export function ManaCurveChart({ points }: { points: ManaCurvePoint[] }) {
  if (!points.length) return null;
  const maxValue = Math.max(6, ...points.map((point) => point.mana_value));
  const buckets = Array.from({ length: maxValue + 1 }, (_, mv) => ({
    mv,
    label: mv === maxValue && maxValue === 6 ? "6+" : String(mv),
    count: points.filter((point) => point.mana_value === mv).reduce((sum, point) => sum + point.card_count, 0)
  }));
  const peak = Math.max(1, ...buckets.map((bucket) => bucket.count));

  return (
    <figure className="chart" aria-labelledby="mana-curve-caption">
      <figcaption id="mana-curve-caption" className="label">Mana curve</figcaption>
      <div className="curve-bars" aria-hidden="true">
        {buckets.map((bucket) => (
          <div key={bucket.mv} className="curve-column">
            <span className="curve-count">{bucket.count || ""}</span>
            <div className="curve-track">
              <div className="curve-bar" style={{ height: `${(bucket.count / peak) * 100}%` }} />
            </div>
            <span className="curve-label">{bucket.label}</span>
          </div>
        ))}
      </div>
      <table className="sr-only">
        <caption>Nonland cards by mana value</caption>
        <thead>
          <tr>
            <th scope="col">Mana value</th>
            <th scope="col">Cards</th>
          </tr>
        </thead>
        <tbody>
          {buckets.map((bucket) => (
            <tr key={bucket.mv}>
              <td>{bucket.label}</td>
              <td>{bucket.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
