import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { MDXRemote } from "next-mdx-remote/rsc";
import remarkGfm from "remark-gfm";

import { AdsProvider } from "@/components/ads-provider";
import { PostCard } from "@/components/blog/post-card";
import { mdxComponentsForPost } from "@/components/blog/mdx-components";
import { EnableAds } from "@/components/enable-ads";
import { GuideView } from "@/components/guide-view";
import {
  articleCredit,
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
import { pageAllowsAds } from "@/lib/ads-policy";
import { DEFAULT_SOCIAL_IMAGE, documentTitle, metaDescription, socialTitle } from "@/lib/seo";

// One dynamic segment serves both /blog/<category> hubs and /blog/<article>.
// Category ids and article slugs never collide (articles carry keywords).
// Next 15 passes route params as a Promise.
type Params = { params: Promise<{ slug: string }> };

// Scheduled posts aren't in the build's static params; they render on first
// request once their date arrives (getPost hides them until then).
export const dynamicParams = true;
export const revalidate = 3600; // BLOG_REVALIDATE_SECONDS

export function generateStaticParams() {
  return [...Object.keys(CATEGORIES), ...allPosts().map((post) => post.slug)].map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  if (isCategory(slug)) {
    const category = CATEGORIES[slug];
    const title = documentTitle(`${category.label} for Magic: The Gathering`);
    const description = metaDescription(category.description);
    return {
      title,
      description,
      alternates: { canonical: `/blog/${slug}` },
      openGraph: {
        type: "website",
        title: socialTitle(`${category.label} for Magic: The Gathering`),
        description,
        url: `/blog/${slug}`,
        siteName: SITE_NAME,
        images: [DEFAULT_SOCIAL_IMAGE],
      },
      twitter: {
        card: "summary_large_image",
        title: socialTitle(`${category.label} for Magic: The Gathering`),
        description,
        images: [DEFAULT_SOCIAL_IMAGE.url],
      },
    };
  }
  const post = getPost(slug);
  if (!post) return {};
  const credit = articleCredit(post);
  const title = documentTitle(post.title);
  const description = metaDescription(post.description);
  const ogTitle = socialTitle(post.title);
  return {
    title,
    description,
    keywords: post.keywords,
    authors: [{ name: credit.byline }],
    alternates: { canonical: `/blog/${post.slug}` },
    robots: post.reviewed ? { index: true, follow: true } : { index: false, follow: true },
    openGraph: {
      type: "article",
      title: ogTitle,
      description,
      url: `/blog/${post.slug}`,
      siteName: SITE_NAME,
      publishedTime: post.date,
      modifiedTime: post.updated,
      authors: [credit.byline],
      images: [DEFAULT_SOCIAL_IMAGE],
    },
    twitter: { card: "summary_large_image", title: ogTitle, description, images: [DEFAULT_SOCIAL_IMAGE.url] },
  };
}

export default async function BlogSlugPage({ params }: Params) {
  const { slug } = await params;
  if (isCategory(slug)) {
    // A category with no published guide yet (e.g. before its first scheduled date) isn't a page.
    if (!postsInCategory(slug).length) notFound();
    return (
      <AdsProvider allow>
        <EnableAds />
        <CategoryHub category={slug} />
      </AdsProvider>
    );
  }
  const post = getPost(slug);
  if (!post) notFound();
  // Archived, draft, and not-yet-published slugs never reach here: getPost
  // omits them, and pageAllowsAds is false for that miss.
  const allowAds = pageAllowsAds(`/blog/${slug}`);
  return (
    <AdsProvider allow={allowAds}>
      {allowAds ? <EnableAds /> : null}
      <Article post={post} />
    </AdsProvider>
  );
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
  const credit = articleCredit(post);
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: post.title,
    description: post.description,
    datePublished: post.date,
    dateModified: post.updated,
    author:
      credit.showMethod && credit.byline === "Deck Lab Editorial"
        ? { "@type": "Organization", name: "Deck Lab Editorial" }
        : { "@type": "Person", name: credit.byline },
    publisher: { "@type": "Organization", name: SITE_NAME, url: SITE_URL },
    mainEntityOfPage: `${SITE_URL}/blog/${post.slug}`,
    keywords: post.keywords.join(", "),
    wordCount: post.wordCount,
  };
  return (
    <main className="shell blog-shell">
      <GuideView slug={post.slug} category={post.category} />
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
            By {credit.byline} · {SITE_NAME} · Published <time dateTime={post.date}>{formatDate(post.date)}</time>
            {post.updated !== post.date ? (
              <>
                {" "}
                · Updated <time dateTime={post.updated}>{formatDate(post.updated)}</time>
              </>
            ) : null}{" "}
            · {post.readingMinutes} min read
            {credit.showMethod ? (
              <>
                {" "}
                · <Link href="/method">How we count</Link>
              </>
            ) : null}
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
            components={mdxComponentsForPost(post.reviewed)}
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
