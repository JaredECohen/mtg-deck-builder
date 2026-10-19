import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { MDXRemote } from "next-mdx-remote/rsc";
import remarkGfm from "remark-gfm";

import { PostCard } from "@/components/blog/post-card";
import { mdxComponents } from "@/components/blog/mdx-components";
import {
  AUTHOR,
  CATEGORIES,
  SITE_NAME,
  SITE_URL,
  allPosts,
  formatDate,
  getPost,
  isCategory,
  postsInCategory,
  relatedPosts,
  type CategoryId,
  type Post,
} from "@/lib/blog";

// One dynamic segment serves both /blog/<category> hubs and /blog/<article>.
// Category ids and article slugs never collide (articles carry keywords).
type Params = { params: { slug: string } };

export const dynamicParams = false;

export function generateStaticParams() {
  return [...Object.keys(CATEGORIES), ...allPosts().map((post) => post.slug)].map((slug) => ({ slug }));
}

export function generateMetadata({ params }: Params): Metadata {
  if (isCategory(params.slug)) {
    const category = CATEGORIES[params.slug];
    return {
      title: `${category.label}: MTG Guides | ${SITE_NAME}`,
      description: category.description,
      alternates: { canonical: `/blog/${params.slug}` },
    };
  }
  const post = getPost(params.slug);
  if (!post) return {};
  return {
    title: `${post.title} | ${SITE_NAME}`,
    description: post.description,
    keywords: post.keywords,
    authors: [{ name: AUTHOR }],
    alternates: { canonical: `/blog/${post.slug}` },
    openGraph: {
      type: "article",
      title: post.title,
      description: post.description,
      url: `/blog/${post.slug}`,
      siteName: SITE_NAME,
      publishedTime: post.date,
      modifiedTime: post.updated,
      authors: [AUTHOR],
    },
    twitter: { card: "summary", title: post.title, description: post.description },
  };
}

export default function BlogSlugPage({ params }: Params) {
  if (isCategory(params.slug)) return <CategoryHub category={params.slug} />;
  const post = getPost(params.slug);
  if (!post) notFound();
  return <Article post={post} />;
}

function CategoryHub({ category }: { category: CategoryId }) {
  const meta = CATEGORIES[category];
  const posts = postsInCategory(category);
  return (
    <main className="shell blog-shell">
      <nav className="blog-breadcrumbs" aria-label="Breadcrumb">
        <Link href="/blog">Guides</Link> <span aria-hidden="true">/</span> <span>{meta.label}</span>
      </nav>
      <header className="blog-header">
        <h1 className="headline">{meta.label}</h1>
        <p className="subhead">{meta.description}</p>
      </header>
      <div className="blog-grid">
        {posts.map((post) => (
          <PostCard key={post.slug} post={post} />
        ))}
      </div>
    </main>
  );
}

function Article({ post }: { post: Post }) {
  const category = CATEGORIES[post.category];
  const related = relatedPosts(post);
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: post.title,
    description: post.description,
    datePublished: post.date,
    dateModified: post.updated,
    author: { "@type": "Person", name: AUTHOR },
    publisher: { "@type": "Organization", name: SITE_NAME, url: SITE_URL },
    mainEntityOfPage: `${SITE_URL}/blog/${post.slug}`,
    keywords: post.keywords.join(", "),
    wordCount: post.wordCount,
  };
  return (
    <main className="shell blog-shell">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      <nav className="blog-breadcrumbs" aria-label="Breadcrumb">
        <Link href="/blog">Guides</Link> <span aria-hidden="true">/</span>{" "}
        <Link href={`/blog/${post.category}`}>{category.label}</Link>
      </nav>
      <article className="blog-article">
        <header className="blog-header">
          <h1 className="headline">{post.title}</h1>
          <p className="subhead">{post.description}</p>
          <p className="blog-byline muted">
            By {AUTHOR} · {SITE_NAME} · Published <time dateTime={post.date}>{formatDate(post.date)}</time>
            {post.updated !== post.date ? (
              <>
                {" "}
                · Updated <time dateTime={post.updated}>{formatDate(post.updated)}</time>
              </>
            ) : null}{" "}
            · {post.readingMinutes} min read
          </p>
        </header>
        {post.toc.length >= 4 ? (
          <nav className="blog-toc" aria-label="Table of contents">
            <strong>In this guide</strong>
            <ol>
              {post.toc.map((entry) => (
                <li key={entry.id}>
                  <a href={`#${entry.id}`}>{entry.title}</a>
                </li>
              ))}
            </ol>
          </nav>
        ) : null}
        <div className="blog-prose">
          <MDXRemote
            source={post.body}
            components={mdxComponents}
            options={{ mdxOptions: { remarkPlugins: [remarkGfm] } }}
          />
        </div>
      </article>
      {related.length ? (
        <section className="blog-related" aria-labelledby="related-heading">
          <h2 id="related-heading">Keep reading</h2>
          <div className="blog-grid">
            {related.map((other) => (
              <PostCard key={other.slug} post={other} />
            ))}
          </div>
        </section>
      ) : null}
    </main>
  );
}
