"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useAccount } from "@/hooks/use-account";
import { analyzeUrl, shareUrl } from "@/hooks/use-saved-decks";
import { deleteSavedDeck, fetchDeckHistory, updateSavedDeck, type DeckVisibility, type SavedDeck } from "@/lib/api";

export function DeckLibrary() {
  const account = useAccount();
  const [decks, setDecks] = useState<SavedDeck[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (account.status !== "in") return;
    let cancelled = false;
    fetchDeckHistory(50)
      .then((rows) => {
        if (!cancelled) setDecks(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load your library");
      });
    return () => {
      cancelled = true;
    };
  }, [account.status]);

  async function rename(deck: SavedDeck, name: string) {
    const next = name.trim();
    if (!next || next === deck.name) return;
    setError(null);
    setBusy(true);
    try {
      const updated = await updateSavedDeck(deck.id, { name: next });
      setDecks((rows) => rows?.map((row) => (row.id === deck.id ? updated : row)) ?? rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not rename the deck");
    } finally {
      setBusy(false);
    }
  }

  async function setVisibility(deck: SavedDeck, visibility: DeckVisibility) {
    setError(null);
    setBusy(true);
    try {
      const updated = await updateSavedDeck(deck.id, { visibility });
      setDecks((rows) => rows?.map((row) => (row.id === deck.id ? updated : row)) ?? rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the deck");
    } finally {
      setBusy(false);
    }
  }

  async function remove(deck: SavedDeck) {
    if (!window.confirm(`Delete "${deck.name}"? Its share link will stop working.`)) return;
    setError(null);
    setBusy(true);
    try {
      await deleteSavedDeck(deck.id);
      setDecks((rows) => rows?.filter((row) => row.id !== deck.id) ?? rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the deck");
    } finally {
      setBusy(false);
    }
  }

  async function deleteAccount() {
    if (!window.confirm("Delete your account and every deck in this library? Share links will stop working.")) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/auth/account", { method: "DELETE" });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(body?.detail ?? "Could not delete the account");
      }
      window.location.assign("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the account");
      setBusy(false);
    }
  }

  if (account.status === "loading") return <p className="muted">Loading…</p>;
  if (account.status === "out") {
    return (
      <>
        <p>Sign in to see decks you have saved to your library. Sharing a deck still works without an account.</p>
        <p>
          <Link className="button button-compact" href="/signin">Sign in</Link>
        </p>
      </>
    );
  }

  return (
    <>
      <p className="muted">Signed in as {account.email}.</p>
      {error ? <p className="workflow-error" role="alert">{error}</p> : null}
      {decks === null ? <p className="muted">Loading your decks…</p> : null}
      {decks && !decks.length ? <p>Nothing saved yet. Build a deck and choose Save &amp; share.</p> : null}
      {decks?.length ? (
        <ul className="card-list library-list">
          {decks.map((deck) => (
            <LibraryRow
              key={deck.id}
              deck={deck}
              busy={busy}
              onRename={rename}
              onVisibility={setVisibility}
              onDelete={remove}
            />
          ))}
        </ul>
      ) : null}
      <p className="library-delete-account">
        <button type="button" className="chip" onClick={() => void deleteAccount()} disabled={busy}>
          Delete account
        </button>
      </p>
    </>
  );
}

function LibraryRow({
  deck,
  busy,
  onRename,
  onVisibility,
  onDelete
}: {
  deck: SavedDeck;
  busy: boolean;
  onRename: (deck: SavedDeck, name: string) => void;
  onVisibility: (deck: SavedDeck, visibility: DeckVisibility) => void;
  onDelete: (deck: SavedDeck) => void;
}) {
  const [name, setName] = useState(deck.name);
  const hidden = deck.visibility === "unlisted";
  return (
    <li className="card-row library-row">
      <form
        className="library-rename"
        onSubmit={(event) => {
          event.preventDefault();
          onRename(deck, name);
        }}
      >
        <label className="sr-only" htmlFor={`rename-${deck.id}`}>Rename {deck.name}</label>
        <input
          id={`rename-${deck.id}`}
          className="input"
          value={name}
          maxLength={200}
          onChange={(event) => setName(event.target.value)}
        />
        <button type="submit" className="chip" disabled={busy || name.trim() === deck.name}>Rename</button>
      </form>
      <p className="muted revision-meta">
        {deck.format} · {new Date(deck.created_at).toLocaleDateString()}
        {hidden ? " · hidden from search" : " · public page"}
      </p>
      <div className="revision-actions">
        <a className="chip" href={shareUrl(deck.share_token)}>View</a>
        <a className="chip" href={analyzeUrl(deck.share_token)}>Open in builder</a>
        <button
          type="button"
          className="chip"
          disabled={busy}
          onClick={() => onVisibility(deck, hidden ? "public" : "unlisted")}
        >
          {hidden ? "Allow search engines" : "Hide from search"}
        </button>
        <button type="button" className="chip" disabled={busy} onClick={() => onDelete(deck)}>
          Delete
        </button>
      </div>
    </li>
  );
}
