import "./globals.css";

import type { Metadata } from "next";
import Script from "next/script";
import type { ReactNode } from "react";

import { SiteFooter } from "@/components/site-footer";
import { ADSENSE_CLIENT } from "@/lib/ads";

export const metadata: Metadata = {
  title: "MTG Deck Builder",
  description: "Generate Magic: The Gathering decks with transparent reasoning.",
  // AdSense site verification reads this tag.
  ...(ADSENSE_CLIENT ? { other: { "google-adsense-account": ADSENSE_CLIENT } } : {}),
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        {children}
        <SiteFooter />
        {ADSENSE_CLIENT ? (
          <Script
            id="adsense"
            async
            strategy="afterInteractive"
            crossOrigin="anonymous"
            src={`https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${ADSENSE_CLIENT}`}
          />
        ) : null}
      </body>
    </html>
  );
}
