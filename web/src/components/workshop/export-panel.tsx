"use client";

import { useId, useState } from "react";

import { useDeckExport } from "@/hooks/use-deck-export";
import type { ExportTarget } from "@/lib/api";
import { copyText, downloadText, slugify } from "@/lib/clipboard";
import type { DeckResponse } from "@/lib/types";

const TARGETS: { value: ExportTarget; label: string }[] = [
  { value: "plain", label: "Plain text" },
  { value: "arena", label: "MTG Arena" },
  { value: "moxfield", label: "Moxfield" },
  { value: "archidekt", label: "Archidekt" },
  { value: "csv", label: "CSV" }
];

export function ExportPanel({ deck }: { deck: DeckResponse }) {
  const selectId = useId();
  const [target, setTarget] = useState<ExportTarget>("plain");
  const exporter = useDeckExport(deck);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  // Only offer copy/download for text that matches the selected target.
  const ready = Boolean(exporter.content) && exporter.target === target;

  async function handleCopy() {
    setCopyState((await copyText(exporter.content)) ? "copied" : "failed");
    setTimeout(() => setCopyState("idle"), 2000);
  }

  function handleDownload() {
    const isCsv = exporter.target === "csv";
    downloadText(`${slugify(deck.title)}-${exporter.target}.${isCsv ? "csv" : "txt"}`, exporter.content, isCsv ? "text/csv" : "text/plain");
  }

  return (
    <section className="panel results-card" aria-labelledby="export-heading">
      <h3 id="export-heading" className="label">Export deck</h3>
      <div className="export-row">
        <label className="sr-only" htmlFor={selectId}>Export format</label>
        <select id={selectId} className="select" value={target} onChange={(event) => setTarget(event.target.value as ExportTarget)}>
          {TARGETS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <button type="button" className="button secondary button-compact" onClick={() => void exporter.run(target)} disabled={exporter.loading}>
          {exporter.loading ? "Building…" : "Build export"}
        </button>
      </div>
      {exporter.error ? <p className="workflow-error" role="alert">{exporter.error}</p> : null}
      {ready ? (
        <>
          <div className="chips export-actions">
            <button type="button" className="chip" onClick={() => void handleCopy()}>
              {copyState === "copied" ? "Copied" : copyState === "failed" ? "Copy failed" : "Copy to clipboard"}
            </button>
            <button type="button" className="chip" onClick={handleDownload}>
              Download .{exporter.target === "csv" ? "csv" : "txt"}
            </button>
          </div>
          <span className="sr-only" role="status">
            {copyState === "copied" ? "Export copied to the clipboard." : copyState === "failed" ? "Could not copy the export." : ""}
          </span>
          <pre className="export-output" aria-label={`${TARGETS.find((option) => option.value === exporter.target)?.label} export`}>
            {exporter.content}
          </pre>
        </>
      ) : (
        <p className="muted" style={{ marginTop: 12 }}>
          Render this list for MTG Arena, Moxfield, Archidekt, plain text or CSV, then copy or download it.
        </p>
      )}
    </section>
  );
}
