import Link from "next/link";

import { AdSlot } from "@/components/ad-slot";
import { ADSENSE_FOOTER_SLOT } from "@/lib/ads";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <AdSlot slot={ADSENSE_FOOTER_SLOT} className="site-footer-ad" />
      <nav className="site-footer-links" aria-label="Site">
        <Link href="/">Deck Lab</Link>
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
