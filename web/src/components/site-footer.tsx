"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdSlot } from "@/components/ad-slot";
import { ADSENSE_FOOTER_SLOT } from "@/lib/ads";

export function SiteFooter() {
  // Fail closed until this page's server HTML opts in with [data-ads="on"].
  const [showAds, setShowAds] = useState(false);
  useEffect(() => {
    setShowAds(document.querySelector("[data-ads='on']") !== null);
  }, []);
  return (
    <footer className="site-footer">
      {showAds ? <AdSlot slot={ADSENSE_FOOTER_SLOT} allowed /> : null}
      <nav className="site-footer-links" aria-label="Site">
        <Link href="/">Deck Builder</Link>
        <Link href="/blog">Guides</Link>
        <Link href="/about">About</Link>
        <Link href="/contact">Contact</Link>
        <Link href="/privacy">Privacy</Link>
      </nav>
      <p className="site-footer-legal">
        MTG Deck Lab is unofficial Fan Content permitted under the Fan Content Policy. Not approved or endorsed by
        Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.
        Card data and images courtesy of Scryfall. Purchase links may earn an affiliate commission.
      </p>
    </footer>
  );
}
