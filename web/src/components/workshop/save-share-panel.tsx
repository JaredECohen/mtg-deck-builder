"use client";

import { useId, useState } from "react";

import { shareUrl, useSaveDeck, useSavedDeckList } from "@/hooks/use-saved-decks";
import type { DeckEvaluation } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import type { DeckResponse } from "@/lib/types";

type Props = {
  deck: DeckResponse;
  evaluation: DeckEvaluation | null;
};

function CopyButton({ text, label }: { text: string; label: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  return (
    <>
      <button
        type="button"
        className="chip"
        aria-label={label}
        onClick={async () => {
          setState((await copyText(text)) ? "copied" : "failed");
          setTimeout(() => setState("idle"), 2000);
        }}
      >
        {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : "Copy link"}
      </button>
      <span className="sr-only" role="status">
        {state === "copied" ? "Link copied to the clipboard." : state === "failed" ? "Could not copy the link." : ""}
      </span>
    </>
  );
}

export function SaveSharePanel({ deck, evaluation }: Props) {
  const linkId = useId();
  const { saved, saving, error, save } = useSaveDeck(deck);
  const savedList = useSavedDeckList();
  const [listOpen, setListOpen] = useState(false);
  const link = saved ? shareUrl(saved.share_token) : "";

  return (
    <section className="panel results-card" aria-labelledby="save-share-heading">
      <h3 id="save-share-heading" className="label">Save &amp; share</h3>
      {!saved ? (
        <>
          <p className="muted field-help">Saves this exact list and gives you a link anyone can open to see and analyze it.</p>
          <button type="button" className="button secondary button-compact" onClick={() => void save(evaluation)} disabled={saving}>
            {saving ? "Saving…" : "Save deck"}
          </button>
        </>
      ) : (
        <div className="share-row">
          <label className="label" htmlFor={linkId}>Share link</label>
          <div className="share-link-row">
            <input
              id={linkId}
              className="input"
              readOnly
              value={link}
              onFocus={(event) => event.currentTarget.select()}
            />
            <CopyButton text={link} label="Copy share link" />
          </div>
          <p className="muted field-help" role="status">Saved as &ldquo;{saved.name}&rdquo;.</p>
        </div>
      )}
      {error ? <p className="workflow-error" role="alert">{error}</p> : null}

      <details
        className="saved-decks"
        onToggle={(event) => {
          const isOpen = event.currentTarget.open;
          setListOpen(isOpen);
          if (isOpen) void savedList.load();
        }}
      >
        <summary>Your saved decks</summary>
        {listOpen && savedList.loading ? <p className="muted">Loading…</p> : null}
        {savedList.error ? <p className="workflow-error" role="alert">{savedList.error}</p> : null}
        {savedList.decks && !savedList.decks.length ? <p className="muted">Nothing saved yet.</p> : null}
        {savedList.decks?.length ? (
          <ul className="card-list saved-deck-list">
            {savedList.decks.map((item) => (
              <li key={item.id} className="card-row saved-deck-row">
                <div className="revision-text">
                  <span>{item.name}</span>
                  <span className="muted revision-meta">
                    {item.format} · {new Date(item.created_at).toLocaleDateString()}
                  </span>
                </div>
                <div className="revision-actions">
                  <a className="chip" href={shareUrl(item.share_token)} aria-label={`Open ${item.name} in Analyze`}>
                    Open
                  </a>
                  <CopyButton text={shareUrl(item.share_token)} label={`Copy share link for ${item.name}`} />
                  <button
                    type="button"
                    className="chip"
                    aria-label={`Delete saved deck ${item.name}`}
                    onClick={() => {
                      if (window.confirm(`Delete "${item.name}"? Its share link will stop working.`)) void savedList.remove(item.id);
                    }}
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </details>
    </section>
  );
}
