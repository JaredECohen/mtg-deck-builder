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

export function useDeckChat() {
  const [bubbles, setBubbles] = useState<ChatBubble[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const reset = useCallback(() => {
    abort.current?.abort();
    setBubbles([]);
    setError(null);
  }, []);

  const send = useCallback(
    async (deck: DeckResponse, message: string) => {
      const trimmed = message.trim();
      if (!trimmed) return;

      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;

      const history = bubbles.map((b) => ({ role: b.role, content: b.content }));
      const userBubble: ChatBubble = { id: `${Date.now()}-u`, role: "user", content: trimmed };
      setBubbles((current) => [...current, userBubble]);
      setSending(true);
      setError(null);

      try {
        const reply = await chatAboutDeck(deck, trimmed, history, controller.signal);
        const assistantBubble: ChatBubble = {
          id: `${Date.now()}-a`,
          role: "assistant",
          content: reply.reply,
          suggestedRefinement: reply.suggested_refinement,
        };
        setBubbles((current) => [...current, assistantBubble]);
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

  // Replace the entire chat with a restored history (used when loading a
  // saved deck whose chat was persisted).
  const restore = useCallback((turns: ChatTurn[]) => {
    abort.current?.abort();
    setError(null);
    setBubbles(
      turns.map((t, i) => ({
        id: `restored-${i}-${t.role}`,
        role: t.role,
        content: t.content,
      }))
    );
  }, []);

  return { bubbles, sending, error, send, reset, markApplied, restore };
}
