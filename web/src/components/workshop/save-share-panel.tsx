"use client";

import { useEffect, useId, useState } from "react";
import Link from "next/link";

import { useAccount } from "@/hooks/use-account";
import {
  analyzeUrl,
  forgetLocalDeck,
  readLocalDecks,
  rememberLocalDeck,
  shareUrl,
  useSaveDeck,
  useSavedDeckList,
  type LocalDeck
} from "@/hooks/use-saved-decks";
import type { DeckEvaluation } from "@/lib/api";
import { deleteSavedDeck } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import { visibilityForNewDeck } from "@/lib/deck-visibility";
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
  const hideId = useId();
  const { saved, saving, error, save } = useSaveDeck(deck);
  const account = useAccount();
  const savedList = useSavedDeckList();
  const [listOpen, setListOpen] = useState(false);
  const [hideFromSearch, setHideFromSearch] = useState(false);
  const [localDecks, setLocalDecks] = useState<LocalDeck[]>([]);
  const [localError, setLocalError] = useState<string | null>(null);
  const link = saved ? shareUrl(saved.share_token) : "";

  useEffect(() => {
    setLocalDecks(readLocalDecks());
  }, []);

  async function onSave() {
    const result = await save(evaluation, visibilityForNewDeck(hideFromSearch));
    if (result && account.status !== "in") setLocalDecks(rememberLocalDeck(result));
    if (result && account.status === "in" && listOpen) void savedList.load();
  }

  async function removeLocal(item: LocalDeck) {
    setLocalError(null);
    try {
      await deleteSavedDeck(item.id, item.edit_secret);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not delete the saved deck";
      if (!/not found/i.test(message)) {
        setLocalError(message);
        return;
      }
    }
    setLocalDecks(forgetLocalDeck(item.id));
  }

  return (
    <section className="panel results-card" aria-labelledby="save-share-heading">
      <h3 id="save-share-heading" className="label">Save &amp; share</h3>
      {!saved ? (
        <>
          <p className="muted field-help">
            Saves this exact list and gives you a page anyone can open. The deck list, mana curve, and per-card notes
            are on that page.
          </p>
          <label className="share-check" htmlFor={hideId}>
            <input
              id={hideId}
              type="checkbox"
              checked={hideFromSearch}
              onChange={(event) => setHideFromSearch(event.target.checked)}
            />
            Hide from search engines (the link still works)
          </label>
          <button type="button" className="button secondary button-compact" onClick={() => void onSave()} disabled={saving}>
            {saving ? "Saving…" : "Save deck"}
          </button>
          {account.status === "out" ? (
            <p className="muted field-help">
              <Link href="/signin">Sign in</Link> to keep a library you can reopen on any device.
            </p>
          ) : null}
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
            <a className="chip" href={shareUrl(saved.share_token)}>View page</a>
          </div>
          <p className="muted field-help" role="status">
            Saved as &ldquo;{saved.name}&rdquo;
            {saved.visibility === "unlisted" ? " — hidden from search engines." : "."}
            {account.status === "in" ? " It’s in your library." : ""}
          </p>
        </div>
      )}
      {error ? <p className="workflow-error" role="alert">{error}</p> : null}

      <details
        className="saved-decks"
        onToggle={(event) => {
          const isOpen = event.currentTarget.open;
          setListOpen(isOpen);
          if (isOpen && account.status === "in") void savedList.load();
        }}
      >
        <summary>
          {account.status === "in" ? "Your library" : account.status === "loading" ? "Saved decks" : "Decks saved in this browser"}
        </summary>
        {account.status === "in" ? (
          <p className="muted field-help">
            <Link href="/library">Open your library</Link> to rename a deck or change who can find it.
          </p>
        ) : account.status === "out" ? (
          <p className="muted field-help">These stay on this browser until you sign in.</p>
        ) : null}
        {listOpen && account.status === "in" && savedList.loading ? <p className="muted">Loading…</p> : null}
        {account.status === "in" && savedList.error ? <p className="workflow-error" role="alert">{savedList.error}</p> : null}
        {localError ? <p className="workflow-error" role="alert">{localError}</p> : null}
        {account.status === "in" && savedList.decks && !savedList.decks.length ? <p className="muted">Nothing saved yet.</p> : null}
        {account.status === "out" && !localDecks.length ? <p className="muted">Nothing saved in this browser yet.</p> : null}
        {account.status === "in" && savedList.decks?.length ? (
          <DeckRows
            rows={savedList.decks.map((item) => ({
              id: item.id,
              name: item.name,
              format: item.format,
              share_token: item.share_token,
              created_at: item.created_at
            }))}
            onDelete={(id) => void savedList.remove(id)}
          />
        ) : null}
        {account.status === "out" && localDecks.length ? (
          <DeckRows
            rows={localDecks}
            onDelete={(id) => {
              const item = localDecks.find((row) => row.id === id);
              if (item) void removeLocal(item);
            }}
          />
        ) : null}
      </details>
    </section>
  );
}

function DeckRows({
  rows,
  onDelete
}: {
  rows: { id: string; name: string; format: string; share_token: string; created_at: string }[];
  onDelete: (id: string) => void;
}) {
  return (
    <ul className="card-list saved-deck-list">
      {rows.map((item) => (
        <li key={item.id} className="card-row saved-deck-row">
          <div className="revision-text">
            <span>{item.name}</span>
            <span className="muted revision-meta">
              {item.format} · {new Date(item.created_at).toLocaleDateString()}
            </span>
          </div>
          <div className="revision-actions">
            <a className="chip" href={shareUrl(item.share_token)}>View</a>
            <a className="chip" href={analyzeUrl(item.share_token)} aria-label={`Open ${item.name} in Analyze`}>
              Open
            </a>
            <CopyButton text={shareUrl(item.share_token)} label={`Copy share link for ${item.name}`} />
            <button
              type="button"
              className="chip"
              aria-label={`Delete saved deck ${item.name}`}
              onClick={() => {
                if (window.confirm(`Delete "${item.name}"? Its share link will stop working.`)) onDelete(item.id);
              }}
            >
              Delete
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}
