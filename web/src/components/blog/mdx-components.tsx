import Link from "next/link";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { AdSlot } from "@/components/ad-slot";
import { ADSENSE_IN_ARTICLE_SLOT } from "@/lib/ads";
import { slugify } from "@/lib/blog";
import type { FormatName } from "@/lib/types";

const FORMATS: FormatName[] = ["standard", "modern", "pioneer", "legacy", "commander"];

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && typeof node === "object" && "props" in node) {
    return textOf((node as { props: { children?: ReactNode } }).props.children);
  }
  return "";
}

/** "Try this in Deck Lab": opens the builder with the format and brief filled in. */
export function DeckLabCTA({
  format,
  brief,
  title = "Try it in Deck Lab",
  children,
}: {
  format?: FormatName;
  brief?: string;
  title?: string;
  children?: ReactNode;
}) {
  const params = new URLSearchParams();
  if (format && FORMATS.includes(format)) params.set("format", format);
  if (brief) params.set("brief", brief);
  const query = params.toString();
  const href = `/${query ? `?${query}` : ""}#builder`;
  return (
    <aside className="blog-cta">
      <strong className="blog-cta-title">{title}</strong>
      <div className="blog-cta-body">
        {children ?? <p>Build a legal, playable deck around this idea and see why each card made the list.</p>}
      </div>
      <Link className="button blog-cta-button" href={href}>
        {brief ? `Build: “${brief}”` : "Open the deck builder"}
      </Link>
    </aside>
  );
}

/** In-article ad break. Renders nothing until AdSense and its slot are configured. */
export function InArticleAd() {
  return <AdSlot slot={ADSENSE_IN_ARTICLE_SLOT} className="blog-ad" />;
}

export function Callout({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <aside className="blog-callout">
      {title ? <strong className="blog-callout-title">{title}</strong> : null}
      <div>{children}</div>
    </aside>
  );
}

function Heading2(props: ComponentPropsWithoutRef<"h2">) {
  const id = slugify(textOf(props.children));
  return (
    <h2 id={id} {...props}>
      <a href={`#${id}`} className="blog-heading-anchor">
        {props.children}
      </a>
    </h2>
  );
}

function Heading3(props: ComponentPropsWithoutRef<"h3">) {
  return <h3 id={slugify(textOf(props.children))} {...props} />;
}

function Anchor({ href = "", ...props }: ComponentPropsWithoutRef<"a">) {
  if (href.startsWith("/")) return <Link href={href} {...props} />;
  return <a href={href} target="_blank" rel="noopener noreferrer" {...props} />;
}

function Table(props: ComponentPropsWithoutRef<"table">) {
  return (
    <div className="blog-table-wrap">
      <table {...props} />
    </div>
  );
}

export const mdxComponents = {
  h2: Heading2,
  h3: Heading3,
  a: Anchor,
  table: Table,
  DeckLabCTA,
  InArticleAd,
  Callout,
};
