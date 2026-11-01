"use client";

import { useEffect, useRef } from "react";

import { useAdsAllowed } from "@/components/ads-provider";
import { ADSENSE_CLIENT, shouldRenderAdSlot } from "@/lib/ads";

declare global {
  interface Window {
    adsbygoogle?: unknown[];
  }
}

// A manual AdSense display unit. Renders nothing until both the publisher ID
// and this unit's slot ID are configured.
export function AdSlot({ slot, className }: { slot: string; className?: string }) {
  const allowed = useAdsAllowed();
  const pushed = useRef(false);
  const render = shouldRenderAdSlot({ allowed, client: ADSENSE_CLIENT, slot });

  useEffect(() => {
    if (!render || pushed.current) return;
    pushed.current = true;
    try {
      (window.adsbygoogle = window.adsbygoogle || []).push({});
    } catch {
      /* ad blocked or script not loaded yet: leave the slot empty */
    }
  }, [render]);

  if (!render) return null;
  return (
    <div className={className} aria-label="Advertisement">
      <ins
        className="adsbygoogle"
        style={{ display: "block" }}
        data-ad-client={ADSENSE_CLIENT}
        data-ad-slot={slot}
        data-ad-format="auto"
        data-full-width-responsive="true"
      />
    </div>
  );
}
