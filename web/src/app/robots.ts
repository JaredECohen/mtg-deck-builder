import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/blog";

export default function robots(): MetadataRoute.Robots {
  return {
    // The API proxy serves JSON for the app, not pages worth indexing.
    rules: [{ userAgent: "*", allow: "/", disallow: "/api/" }],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
