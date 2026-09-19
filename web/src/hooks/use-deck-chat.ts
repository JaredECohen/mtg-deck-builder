"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { chatAboutDeck } from "@/lib/api";
import type { ChatTurn } from "@/lib/api";
import type { DeckResponse } from "@/lib/types";

export type ChatBubble = {
  id: string;
  role: "user" | "assistant";
  content: string;
  suggestedRefinement?: string | null;
  applied?: boolean;
};

let bubbleSeq = 0;
function nextId(role: ChatBubble["role"]): string {
  bubbleSeq += 1;
  return `${Date.now()}-${bubbleSeq}-${role}`;
}

/**
 * Conversation about the deck currently on screen.
 *
 * The API is stateless: every turn sends the current deck plus this transcript,
 * so nothing is persisted here. The transcript lives with the results panel and
 * is cleared by the caller when a different deck arrives.
 */
export function useDeckChat() {
  const [bubbles, setBubbles] = useState<ChatBubble[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const reset = useCallback(() => {
    abort.current?.abort();
    setBubbles([]);
    setSending(false);
    setError(null);
  }, []);

  const send = useCallback(
    async (deck: DeckResponse, message: string) => {
      const trimmed = message.trim();
      if (!trimmed) return;

      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;

      const history: ChatTurn[] = bubbles.map((b) => ({ role: b.role, content: b.content }));
      setBubbles((current) => [...current, { id: nextId("user"), role: "user", content: trimmed }]);
      setSending(true);
      setError(null);

      try {
        const reply = await chatAboutDeck(deck, trimmed, history, controller.signal);
        setBubbles((current) => [
          ...current,
          {
            id: nextId("assistant"),
            role: "assistant",
            content: reply.reply,
            suggestedRefinement: reply.suggested_refinement,
          },
        ]);
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Chat failed");
      } finally {
        if (!controller.signal.aborted) setSending(false);
      }
    },
    [bubbles]
  );

  const markApplied = useCallback((id: string) => {
    setBubbles((current) => current.map((b) => (b.id === id ? { ...b, applied: true } : b)));
  }, []);

  return { bubbles, sending, error, send, reset, markApplied };
}
