"use client";

import { createContext, useContext, type ReactNode } from "react";

// Fail closed. A page opts in with <AdsProvider allow>; otherwise no slot renders.
const AdsAllowedContext = createContext(false);

/** Unreviewed, missing, and noindex pages leave this false. */
export function AdsProvider({ allow, children }: { allow: boolean; children: ReactNode }) {
  return <AdsAllowedContext.Provider value={allow}>{children}</AdsAllowedContext.Provider>;
}

export function useAdsAllowed(): boolean {
  return useContext(AdsAllowedContext);
}
