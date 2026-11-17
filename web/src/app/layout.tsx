import "./globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AdsProvider } from "@/components/ads-provider";
import { SiteAnalytics } from "@/components/site-analytics";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { ADSENSE_CLIENT } from "@/lib/ads";
import { SITE_NAME, SITE_URL } from "@/lib/blog";
import { DEFAULT_SOCIAL_IMAGE, HOME_DESCRIPTION, HOME_TITLE } from "@/lib/seo";

// Site-wide defaults only. A page's openGraph replaces this object, so the
// homepage sets its own url, title, and description (app/page.tsx) and other
// pages do not inherit them. Icons come from app/icon.tsx, app/apple-icon.png,
// and app/favicon.ico.
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: HOME_TITLE,
  description: HOME_DESCRIPTION,
  openGraph: {
    type: "website",
    siteName: SITE_NAME,
    images: [DEFAULT_SOCIAL_IMAGE],
  },
  twitter: {
    card: "summary_large_image",
    images: [DEFAULT_SOCIAL_IMAGE.url],
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
