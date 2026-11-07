import "./globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AdsProvider } from "@/components/ads-provider";
import { SiteAnalytics } from "@/components/site-analytics";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { ADSENSE_CLIENT } from "@/lib/ads";
import { SITE_NAME, SITE_URL } from "@/lib/blog";
import { DEFAULT_SOCIAL_IMAGE } from "@/lib/seo";

const HOME_TITLE = "MTG Deck Lab: Free Magic: The Gathering Deck Builder";
const HOME_DESCRIPTION =
  "Build legal Magic: The Gathering decks for Standard, Pioneer, Modern, Legacy and Commander, with a reason for every card, a mana curve and a price.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: HOME_TITLE,
  description: HOME_DESCRIPTION,
  openGraph: {
    type: "website",
    siteName: SITE_NAME,
    title: HOME_TITLE,
    description: HOME_DESCRIPTION,
    url: `${SITE_URL}/`,
    images: [DEFAULT_SOCIAL_IMAGE],
  },
  twitter: {
    card: "summary_large_image",
    title: HOME_TITLE,
    description: HOME_DESCRIPTION,
    images: [DEFAULT_SOCIAL_IMAGE.url],
  },
  icons: {
    icon: [{ url: "/icon", type: "image/png", sizes: "32x32" }],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
  // AdSense site verification reads this tag. The ads script itself is not here.
  ...(ADSENSE_CLIENT ? { other: { "google-adsense-account": ADSENSE_CLIENT } } : {}),
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/* Impact (TCGplayer affiliate program) site verification. It reads
            `value`, not `content`, so it can't go through `metadata.other`. */}
        <meta name="impact-site-verification" {...{ value: "0cca02c1-3e06-41f9-b6c2-5deba4489091" }} />
        {/* The AdSense script is not here. Reviewed guides, the guides index,
            and category hubs render <EnableAds />. Other pages stay ad-free. */}
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
