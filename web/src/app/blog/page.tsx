import type { Metadata } from "next";
import Link from "next/link";

import { PostCard } from "@/components/blog/post-card";
import { EnableAds } from "@/components/enable-ads";
import { CATEGORIES, SITE_NAME, postsInCategory, type CategoryId } from "@/lib/blog";
import { DEFAULT_SOCIAL_IMAGE, documentTitle, metaDescription, socialTitle } from "@/lib/seo";

// Re-render hourly so scheduled guides appear on their date (BLOG_REVALIDATE_SECONDS).
export const revalidate = 3600;

const BLOG_TITLE = "Magic: The Gathering Guides";
const BLOG_DESCRIPTION =
  "Free, in-depth Magic: The Gathering guides: how to play, every major format, deck archetypes, Commander deckbuilding, mulligans and sideboarding.";

export const metadata: Metadata = {
  title: documentTitle(BLOG_TITLE),
  description: metaDescription(BLOG_DESCRIPTION),
  alternates: { canonical: "/blog", types: { "application/rss+xml": "/blog/rss.xml" } },
  openGraph: {
    type: "website",
    title: socialTitle(BLOG_TITLE),
    description: metaDescription(BLOG_DESCRIPTION),
    url: "/blog",
    siteName: SITE_NAME,
    images: [DEFAULT_SOCIAL_IMAGE],
  },
  twitter: {
    card: "summary_large_image",
    title: socialTitle(BLOG_TITLE),
    description: metaDescription(BLOG_DESCRIPTION),
    images: [DEFAULT_SOCIAL_IMAGE.url],
  },
};

export default function BlogIndexPage() {
  const categories = (Object.keys(CATEGORIES) as CategoryId[]).filter((id) => postsInCategory(id).length > 0);
  return (
    <main className="shell blog-shell">
      <EnableAds />
      <header className="blog-header">
        <div className="eyebrow">Guides</div>
        <h1 className="headline">Learn Magic: The Gathering</h1>
        <p className="subhead">
          Plain-language guides for new and returning players: the rules, the formats, how decks are built, and how to
          win more games. Every guide links straight into the deck builder so you can try the idea yourself.
        </p>
        <nav className="blog-category-nav" aria-label="Guide categories">
          {categories.map((id) => (
            <Link key={id} className="chip" href={`/blog/${id}`}>
              {CATEGORIES[id].label}
            </Link>
          ))}
        </nav>
      </header>
      {categories.map((id) => {
        const posts = postsInCategory(id);
        return (
          <section key={id} className="blog-section" aria-labelledby={`cat-${id}`}>
            <div className="blog-section-head">
              <h2 id={`cat-${id}`}>{CATEGORIES[id].label}</h2>
              <Link href={`/blog/${id}`} className="muted">
                All {CATEGORIES[id].label.toLowerCase()} guides →
              </Link>
            </div>
            <p className="muted">{CATEGORIES[id].description}</p>
            <div className="blog-grid">
              {posts.map((post) => (
                <PostCard key={post.slug} post={post} showCategory={false} />
              ))}
            </div>
          </section>
        );
      })}
    </main>
  );
}
