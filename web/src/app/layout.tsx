import "./globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { ADSENSE_CLIENT } from "@/lib/ads";

export const metadata: Metadata = {
  metadataBase: new URL("https://mtgdecklab.app"),
  title: "MTG Deck Lab: Free Magic: The Gathering Deck Builder",
  description:
    "Build legal Magic: The Gathering decks for Standard, Pioneer, Modern, Legacy and Commander, with a reason for every card, a mana curve and a price.",
  // AdSense site verification reads this tag.
  ...(ADSENSE_CLIENT ? { other: { "google-adsense-account": ADSENSE_CLIENT } } : {}),
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/* Impact (TCGplayer affiliate program) site verification. It reads
            `value`, not `content`, so it can't go through `metadata.other`. */}
        <meta name="impact-site-verification" {...{ value: "0cca02c1-3e06-41f9-b6c2-5deba4489091" }} />
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
        <SiteHeader />
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
