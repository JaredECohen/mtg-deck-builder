import Link from "next/link";

import { CATEGORIES, type PostMeta } from "@/lib/blog";

export function PostCard({ post, showCategory = true }: { post: PostMeta; showCategory?: boolean }) {
  return (
    <article className="panel blog-card">
      {showCategory ? <span className="eyebrow">{CATEGORIES[post.category].label}</span> : null}
      <h3 className="blog-card-title">
        <Link href={`/blog/${post.slug}`}>{post.title}</Link>
      </h3>
      <p className="muted">{post.description}</p>
      <span className="muted blog-card-meta">{post.readingMinutes} min read</span>
    </article>
  );
}
