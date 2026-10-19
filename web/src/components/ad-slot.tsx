"use client";

import { useEffect, useRef } from "react";

import { ADSENSE_CLIENT } from "@/lib/ads";

declare global {
  interface Window {
    adsbygoogle?: unknown[];
  }
}

// A manual AdSense display unit. Renders nothing until both the publisher ID
// and this unit's slot ID are configured.
export function AdSlot({ slot, className }: { slot: string; className?: string }) {
  const pushed = useRef(false);

  useEffect(() => {
    if (!ADSENSE_CLIENT || !slot || pushed.current) return;
    pushed.current = true;
    try {
      (window.adsbygoogle = window.adsbygoogle || []).push({});
    } catch {
      /* ad blocked or script not loaded yet: leave the slot empty */
    }
  }, [slot]);

  if (!ADSENSE_CLIENT || !slot) return null;
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
