import type { Metadata } from "next";
import Link from "next/link";

import { PostCard } from "@/components/blog/post-card";
import { CATEGORIES, SITE_NAME, postsInCategory, type CategoryId } from "@/lib/blog";

// Re-render hourly so scheduled guides appear on their date (BLOG_REVALIDATE_SECONDS).
export const revalidate = 3600;

export const metadata: Metadata = {
  title: `Magic: The Gathering Guides | ${SITE_NAME}`,
  description:
    "Free, in-depth Magic: The Gathering guides: how to play, every major format, deck archetypes, Commander deckbuilding, mulligans and sideboarding.",
  alternates: { canonical: "/blog", types: { "application/rss+xml": "/blog/rss.xml" } },
};

export default function BlogIndexPage() {
  const categories = (Object.keys(CATEGORIES) as CategoryId[]).filter((id) => postsInCategory(id).length > 0);
  return (
    <main className="shell blog-shell">
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
