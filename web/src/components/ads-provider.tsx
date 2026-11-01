"use client";

import { createContext, useContext, type ReactNode } from "react";

const AdsAllowedContext = createContext(true);

/** Pages that are unreviewed or noindex set allow to false for the whole tree. */
export function AdsProvider({ allow, children }: { allow: boolean; children: ReactNode }) {
  return <AdsAllowedContext.Provider value={allow}>{children}</AdsAllowedContext.Provider>;
}

export function useAdsAllowed(): boolean {
  return useContext(AdsAllowedContext);
}
