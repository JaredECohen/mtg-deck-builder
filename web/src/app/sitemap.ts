import type { MetadataRoute } from "next";

import { CATEGORIES, SITE_URL, allPosts } from "@/lib/blog";

// Re-render hourly so scheduled guides appear on their date (BLOG_REVALIDATE_SECONDS).
export const revalidate = 3600;

export default function sitemap(): MetadataRoute.Sitemap {
  const posts = allPosts();
  const newest = posts[0]?.updated ?? new Date().toISOString().slice(0, 10);
  const pages: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/`, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/blog`, lastModified: newest, changeFrequency: "weekly", priority: 0.9 },
    ...Object.keys(CATEGORIES)
      .filter((id) => posts.some((post) => post.category === id))
      .map((id) => ({
        url: `${SITE_URL}/blog/${id}`,
        lastModified: newest,
        changeFrequency: "weekly" as const,
        priority: 0.7,
      })),
    ...posts.map((post) => ({
      url: `${SITE_URL}/blog/${post.slug}`,
      lastModified: post.updated,
      changeFrequency: "monthly" as const,
      priority: 0.8,
    })),
    { url: `${SITE_URL}/about`, changeFrequency: "yearly", priority: 0.4 },
    { url: `${SITE_URL}/contact`, changeFrequency: "yearly", priority: 0.3 },
    { url: `${SITE_URL}/privacy`, changeFrequency: "yearly", priority: 0.2 },
  ];
  return pages;
}
