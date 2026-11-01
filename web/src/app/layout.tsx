import "./globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AdsProvider } from "@/components/ads-provider";
import { SiteAnalytics } from "@/components/site-analytics";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { ADSENSE_CLIENT } from "@/lib/ads";
import { SITE_URL } from "@/lib/blog";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
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
        {/* The AdSense script is not here. Each indexable page renders
            <EnableAds /> so a missing or unreviewed guide cannot inherit it. */}
      </head>
      <body>
        <AdsProvider allow={false}>
          <SiteHeader />
          {children}
          <SiteFooter />
          <SiteAnalytics />
        </AdsProvider>
      </body>
    </html>
  );
}
