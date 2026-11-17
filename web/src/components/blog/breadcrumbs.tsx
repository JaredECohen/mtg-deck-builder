import Link from "next/link";

import { SITE_URL } from "@/lib/blog";

export type Crumb = { label: string; href?: string };

/** Home → Guides → section → article. The current page is not a link. */
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: item.label,
      ...(item.href ? { item: `${SITE_URL}${item.href}` } : {}),
    })),
  };
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      <nav className="blog-breadcrumbs" aria-label="Breadcrumb">
        {items.map((item, index) => {
          const current = index === items.length - 1;
          return (
            <span key={`${item.label}-${index}`}>
              {index > 0 ? <span aria-hidden="true"> / </span> : null}
              {item.href && !current ? (
                <Link href={item.href}>{item.label}</Link>
              ) : (
                <span aria-current={current ? "page" : undefined}>{item.label}</span>
              )}
            </span>
          );
        })}
      </nav>
    </>
  );
}
