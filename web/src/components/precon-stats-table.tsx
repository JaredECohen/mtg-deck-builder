"use client";

// Value import: `tsx --test` compiles JSX to React.createElement.
import React, { useState } from "react";

import {
  COLOR_LABELS,
  COLOR_ORDER,
  defaultSortDirection,
  filterPreconRows,
  formatAverage,
  formatMoney,
  sortPreconRows,
  type PreconSetOption,
  type PreconSortKey,
  type PreconStatsRow,
  type SortDirection,
} from "@/lib/precon-stats-shared";

const COLUMNS: { key: PreconSortKey; label: string; numeric: boolean; note?: string }[] = [
  { key: "name", label: "Deck", numeric: false },
  { key: "setCode", label: "Set", numeric: false },
  { key: "releaseDate", label: "Released", numeric: false },
  { key: "colors", label: "Colors", numeric: false },
  { key: "commanders", label: "Commander", numeric: false },
  { key: "landCount", label: "Lands", numeric: true },
  { key: "averageManaValue", label: "Avg MV", numeric: true, note: "nonland, 7+ as 7" },
  { key: "curve", label: "Curve", numeric: false, note: "MV 0–7+" },
  { key: "rampCount", label: "Ramp", numeric: true },
  { key: "drawCount", label: "Draw", numeric: true },
  { key: "removalCount", label: "Removal", numeric: true },
  { key: "gameChangerCount", label: "Game Changers", numeric: true },
  { key: "priceUsd", label: "Price", numeric: true },
];

function ColorPips({ colors }: { colors: string[] }) {
  if (!colors.length) return <span className="muted">Colorless</span>;
  return (
    <span className="color-pips">
      {colors.map((color) => (
        <span key={color} className={`color-pip pip-${color.toLowerCase()}`} title={COLOR_LABELS[color as keyof typeof COLOR_LABELS]}>
          <span className="sr-only">{COLOR_LABELS[color as keyof typeof COLOR_LABELS]}</span>
          <span aria-hidden="true">{color}</span>
        </span>
      ))}
    </span>
  );
}

function curveLabel(curve: number[]): string {
  return curve.map((count, manaValue) => `mana value ${manaValue === 7 ? "7 or more" : manaValue}: ${count}`).join(", ");
}

export function PreconStatsTable({
  rows,
  sets,
  priceDate,
}: {
  rows: PreconStatsRow[];
  sets: PreconSetOption[];
  priceDate: string;
}) {
  const [sortKey, setSortKey] = useState<PreconSortKey>("releaseDate");
  const [direction, setDirection] = useState<SortDirection>("desc");
  const [colors, setColors] = useState<string[]>([]);
  const [colorless, setColorless] = useState(false);
  const [setCode, setSetCode] = useState("");
  const shown = sortPreconRows(filterPreconRows(rows, { colors, colorless, setCode }), sortKey, direction);

  function toggleColor(color: string) {
    setColorless(false);
    setColors((current) => (current.includes(color) ? current.filter((item) => item !== color) : [...current, color]));
  }

  function onSort(key: PreconSortKey) {
    if (key === sortKey) {
      setDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setDirection(defaultSortDirection(key));
  }

  return (
    <div className="precon-stats-browser">
      <div className="precon-filters">
        <fieldset className="precon-filter-colors">
          <legend className="label">Includes colors</legend>
          <div className="chips">
            {COLOR_ORDER.map((color) => (
              <button
                key={color}
                type="button"
                className={colors.includes(color) && !colorless ? "chip active" : "chip"}
                aria-pressed={colors.includes(color) && !colorless}
                onClick={() => toggleColor(color)}
              >
                {COLOR_LABELS[color]}
              </button>
            ))}
            <button
              type="button"
              className={colorless ? "chip active" : "chip"}
              aria-pressed={colorless}
              onClick={() => {
                setColorless((current) => !current);
                setColors([]);
              }}
            >
              Colorless
            </button>
          </div>
        </fieldset>
        <label className="precon-filter-set">
          <span className="label">Set</span>
          <select className="select precon-set-select" value={setCode} onChange={(event) => setSetCode(event.target.value)}>
            <option value="">All sets ({rows.length})</option>
            {sets.map((set) => (
              <option key={set.code} value={set.code}>
                {set.code} ({set.decks})
              </option>
            ))}
          </select>
        </label>
        <p className="muted precon-filter-count">
          Showing {shown.length} of {rows.length}. Filters and sorting run in the browser. Without JavaScript the full
          table stays in release-date order, newest first.
        </p>
      </div>
      <div className="table-scroll">
        <table className="data-table precon-stats-table">
          <caption className="sr-only">
            Official Commander precon decks, one row per product, sorted by release date unless a column button changes it.
            Price is the {priceDate} Scryfall snapshot.
          </caption>
          <thead>
            <tr>
              {COLUMNS.map((column) => {
                const active = column.key === sortKey;
                const aria = active ? (direction === "asc" ? "ascending" : "descending") : "none";
                return (
                  <th key={column.key} aria-sort={aria} scope="col" className={column.numeric ? "num" : undefined}>
                    <button type="button" className="precon-sort" onClick={() => onSort(column.key)}>
                      {column.label}
                      {column.key === "priceUsd" ? <span className="precon-col-note">{priceDate}</span> : null}
                      {column.note ? <span className="precon-col-note">{column.note}</span> : null}
                      <span className="sr-only">
                        {active ? (direction === "asc" ? ", sorted ascending" : ", sorted descending") : ", sort"}
                      </span>
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.length ? (
              shown.map((row) => (
                <tr key={row.id}>
                  <th scope="row">
                    {row.href ? <a href={row.href}>{row.name}</a> : row.name}
                    {row.isReprint && row.reprintOfName && row.reprintOfRelease ? (
                      <span className="precon-reprint">
                        Same list as {row.reprintOfName}, {row.reprintOfRelease}
                      </span>
                    ) : null}
                  </th>
                  <td>{row.setCode}</td>
                  <td>
                    <time dateTime={row.releaseDate}>{row.releaseDate}</time>
                  </td>
                  <td>
                    <ColorPips colors={row.colors} />
                  </td>
                  <td>{row.commanders.join(", ")}</td>
                  <td className="num">{row.landCount}</td>
                  <td className="num">{formatAverage(row.averageManaValue)}</td>
                  <td className="num precon-curve" title={curveLabel(row.curve)}>
                    {row.curve.join(" ")}
                    <span className="sr-only">{curveLabel(row.curve)}</span>
                  </td>
                  <td className="num">{row.rampCount}</td>
                  <td className="num">{row.drawCount}</td>
                  <td className="num">{row.removalCount}</td>
                  <td className="num">
                    {row.gameChangerCount}
                    {row.gameChangers.length ? <span className="precon-gc-names">{row.gameChangers.join(", ")}</span> : null}
                  </td>
                  <td className="num">
                    {formatMoney(row.priceUsd)}
                    {row.pricePartial ? <span className="precon-price-note">partial, {row.unpricedCount} unpriced</span> : null}
                    {row.foilCommanders.length ? (
                      <span className="precon-price-note">foil commander: {row.foilCommanders.join(", ")}</span>
                    ) : null}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={COLUMNS.length}>No decks match these filters.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
