import "./globals.css";

import type { Metadata } from "next";
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
      <head>
        {/* A literal <script> in the server HTML, not next/script: that only
            emits a <link rel="preload"> and injects the tag client-side, and
            AdSense's "code snippet" verification reads the raw HTML. */}
        {ADSENSE_CLIENT ? (
          <script
            async
            crossOrigin="anonymous"
            src={`https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${ADSENSE_CLIENT}`}
          />
        ) : null}
      </head>
      <body>
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
