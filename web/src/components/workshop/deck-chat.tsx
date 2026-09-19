"use client";

import { useEffect, useRef, useState } from "react";

import type { ChatBubble } from "@/hooks/use-deck-chat";

type Props = {
  bubbles: ChatBubble[];
  sending: boolean;
  error: string | null;
  /** True while the parent is applying a refinement; disables the apply buttons. */
  refining: boolean;
  onSend: (message: string) => void;
  /** Apply the proposed change to the deck right away. */
  onApplyRefinement: (bubbleId: string, refinement: string) => void;
  /** Put the proposed change in the Refine box without applying it. */
  onEditRefinement: (refinement: string) => void;
  onClear: () => void;
};

const EXAMPLES = [
  "What's the win condition?",
  "Why 4x Lightning Bolt and not 2x?",
  "Make it cheaper without losing pressure.",
  "Swap the artifacts for more removal.",
];

export function DeckChat({
  bubbles,
  sending,
  error,
  refining,
  onSend,
  onApplyRefinement,
  onEditRefinement,
  onClear,
}: Props) {
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [bubbles, sending]);

  function submit() {
    if (!draft.trim() || sending) return;
    onSend(draft);
    setDraft("");
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div className="panel results-card deck-chat">
      <div className="deck-chat-header">
        <span className="label" style={{ marginBottom: 0 }}>Ask About This Deck</span>
        <span className="muted" style={{ fontSize: 12 }}>
          Ask anything. If your message asks for a change, you get a one-click apply.
        </span>
        {bubbles.length ? (
          <button type="button" className="chip" onClick={onClear} disabled={sending}>
            Clear
          </button>
        ) : null}
      </div>

      <div className="deck-chat-messages" ref={listRef}>
        {bubbles.length === 0 ? (
          <div className="deck-chat-empty">
            <p>Try:</p>
            <ul>
              {EXAMPLES.map((example) => (
                <li key={example}>
                  <button type="button" className="card-button" onClick={() => setDraft(example)}>
                    &ldquo;{example}&rdquo;
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {bubbles.map((bubble) => (
          <div key={bubble.id} className={`deck-chat-bubble ${bubble.role}`}>
            <div className="deck-chat-bubble-body">{bubble.content}</div>
            {bubble.role === "assistant" && bubble.suggestedRefinement ? (
              <div className="deck-chat-apply-row">
                <div className="deck-chat-apply-label">Proposed change:</div>
                <div className="deck-chat-apply-text">{bubble.suggestedRefinement}</div>
                <button
                  type="button"
                  className="button secondary deck-chat-apply-btn"
                  disabled={refining || bubble.applied}
                  onClick={() => onApplyRefinement(bubble.id, bubble.suggestedRefinement as string)}
                >
                  {bubble.applied ? "Applied" : refining ? "Applying…" : "Apply to deck"}
                </button>
                {!bubble.applied ? (
                  <button
                    type="button"
                    className="chip"
                    disabled={refining}
                    onClick={() => onEditRefinement(bubble.suggestedRefinement as string)}
                  >
                    Edit first
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        ))}

        {sending ? (
          <div className="deck-chat-bubble assistant">
            <div className="deck-chat-bubble-body muted">Thinking…</div>
          </div>
        ) : null}
      </div>

      {error ? <div className="deck-chat-error">{error}</div> : null}

      <div className="deck-chat-input-row">
        <textarea
          className="textarea deck-chat-input"
          rows={2}
          placeholder="Ask about the deck, or describe a change…"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={sending}
        />
        <button type="button" className="button deck-chat-send" onClick={submit} disabled={sending || !draft.trim()}>
          {sending ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
