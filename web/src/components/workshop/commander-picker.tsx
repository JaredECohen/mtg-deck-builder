"use client";

import { useEffect } from "react";

import { useCommanderProfile, useCommanderSearch, type CommanderSort } from "@/hooks/use-commander-search";
import type { CommanderProfile, FormatName } from "@/lib/types";

export type CommanderMode = "recommend" | "selected";

type Props = {
  format: FormatName;
  colors: string[];
  playstyleTags: string[];
  themeTags: string[];
  selectedCommanderName: string;
  commanderMode: CommanderMode;
  commanderSearch: string;
  commanderSort: CommanderSort;
  onModeChange: (mode: CommanderMode) => void;
  onSearchChange: (value: string) => void;
  onSortChange: (sort: CommanderSort) => void;
  onSelect: (name: string) => void;
  onOpenCard: (name: string) => void;
  onProfileChange?: (profile: CommanderProfile | null) => void;
};

export function CommanderPicker({
  format,
  colors,
  playstyleTags,
  themeTags,
  selectedCommanderName,
  commanderMode,
  commanderSearch,
  commanderSort,
  onModeChange,
  onSearchChange,
  onSortChange,
  onSelect,
  onOpenCard,
  onProfileChange
}: Props) {
  const { commanders, loading } = useCommanderSearch({
    format,
    colors,
    playstyleTags,
    themeTags,
    search: commanderSearch,
    sort: commanderSort,
    enabled: format === "commander"
  });
  const { profile } = useCommanderProfile(selectedCommanderName, format === "commander" && commanderMode === "selected");

  useEffect(() => {
    onProfileChange?.(profile);
  }, [profile, onProfileChange]);

  if (format !== "commander") return null;

  return (
    <>
      <div className="panel form-card panel-strong">
        <span className="label">Commander Mode</span>
        <div className="chips">
          <button type="button" className={`chip ${commanderMode === "recommend" ? "active" : ""}`} onClick={() => onModeChange("recommend")}>
            Recommend Commander
          </button>
          <button type="button" className={`chip ${commanderMode === "selected" ? "active" : ""}`} onClick={() => onModeChange("selected")}>
            I&apos;ll Choose
          </button>
        </div>
        <p className="muted" style={{ marginTop: 12 }}>
          Browse ranked commanders, filter them by colors and playstyle, then lock one in for deck generation.
        </p>
      </div>
      <div className="panel form-card">
        <div className="export-row" style={{ alignItems: "center" }}>
          <label className="label" htmlFor="commander-search" style={{ marginBottom: 0 }}>Commander Search</label>
          <select className="select" value={commanderSort} onChange={(event) => onSortChange(event.target.value as CommanderSort)}>
            <option value="match">Best Match</option>
            <option value="popularity">Popularity</option>
            <option value="support">Support Depth</option>
            <option value="name">Name</option>
          </select>
        </div>
        <input
          id="commander-search"
          className="input"
          value={commanderSearch}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Search any legal commander"
        />
        <div className="card-list" style={{ marginTop: 12, maxHeight: 340, overflowY: "auto" }}>
          {loading ? <p className="muted">Ranking commanders...</p> : null}
          {!loading && !commanders.length ? <p className="muted">No commanders matched the current filters.</p> : null}
          {commanders.map((commander) => {
            const isSelected = selectedCommanderName === commander.name;
            return (
              <div key={commander.name} className="card-row" style={{ display: "block" }}>
                <div className="export-row" style={{ alignItems: "center" }}>
                  <button
                    type="button"
                    className={`card-button ${isSelected ? "active" : ""}`}
                    onClick={() => {
                      onSelect(commander.name);
                      onModeChange("selected");
                    }}
                    style={{ flex: 1, textAlign: "left" }}
                  >
                    <span>{commander.name}{isSelected ? " ✓" : ""}</span>
                    <span className="muted">
                      {commander.colors.join("") || "Colorless"} • support {commander.support_depth} • pop {commander.popularity.toFixed(0)}
                    </span>
                  </button>
                  <button type="button" className="chip" onClick={() => onOpenCard(commander.name)}>View Card</button>
                </div>
                <p className="muted" style={{ marginTop: 8 }}>{commander.strategy_summary}</p>
                {commander.tags.length ? <p className="muted" style={{ marginTop: 6 }}>Tags: {commander.tags.slice(0, 5).join(", ")}</p> : null}
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
