import type { MetadataRoute } from "next";

import { SITE_URL, indexablePosts, indexableStaticPaths } from "@/lib/blog";
import { fetchPublicDeckIndex } from "@/lib/public-deck";

// Re-render hourly so scheduled guides appear on their date (BLOG_REVALIDATE_SECONDS).
export const revalidate = 3600;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const posts = indexablePosts();
  const newest = posts[0]?.updated ?? new Date().toISOString().slice(0, 10);
  const postByPath = new Map(posts.map((post) => [`/blog/${post.slug}`, post]));
  const pages: MetadataRoute.Sitemap = indexableStaticPaths().map((path) => {
    if (path === "/") return { url: `${SITE_URL}/`, changeFrequency: "weekly", priority: 1 };
    if (path === "/blog") return { url: `${SITE_URL}/blog`, lastModified: newest, changeFrequency: "weekly", priority: 0.9 };
    const post = postByPath.get(path);
    if (post) {
      return {
        url: `${SITE_URL}${path}`,
        lastModified: post.updated,
        changeFrequency: "monthly",
        priority: 0.8,
      };
    }
    if (path.startsWith("/blog/")) {
      return { url: `${SITE_URL}${path}`, lastModified: newest, changeFrequency: "weekly", priority: 0.7 };
    }
    const priority = path === "/method" || path === "/about" ? 0.4 : path === "/contact" ? 0.3 : 0.2;
    return { url: `${SITE_URL}${path}`, changeFrequency: "yearly", priority };
  });
  // Public decks only. Unlisted (noindex) decks are omitted by the API.
  const shared = await fetchPublicDeckIndex();
  for (const deck of shared) {
    pages.push({
      url: `${SITE_URL}/d/${encodeURIComponent(deck.share_token)}`,
      ...(deck.updated_at ? { lastModified: deck.updated_at } : {}),
      changeFrequency: "weekly",
      priority: 0.6
    });
  }
  return pages;
}
