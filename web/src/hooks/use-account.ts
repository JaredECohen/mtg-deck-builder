"use client";

import { useEffect, useState } from "react";

import { accountFromMePayload } from "@/lib/account-payload";

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
        const account = accountFromMePayload(await response.json().catch(() => null));
        if (account === "reauth" && window.location.pathname !== "/signin") {
          window.location.assign("/signin?error=expired");
          return null;
        }
        return account === "reauth" ? null : account;
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
