"use client";

import { useEffect, useState } from "react";

export type AccountState =
  | { status: "loading" }
  | { status: "out" }
  | { status: "in"; id: string; email: string };

export function useAccount(): AccountState {
  const [state, setState] = useState<AccountState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetch("/api/auth/me")
      .then(async (response) => {
        if (!response.ok) return null;
        const body = (await response.json()) as { user?: { id?: unknown; email?: unknown } };
        if (typeof body.user?.id !== "string" || typeof body.user.email !== "string") return null;
        return { id: body.user.id, email: body.user.email };
      })
      .catch(() => null)
      .then((user) => {
        if (cancelled) return;
        setState(user ? { status: "in", id: user.id, email: user.email } : { status: "out" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
