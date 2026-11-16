import { getPost, isCategory } from "@/lib/blog";

/**
 * True when this path may load AdSense. Ads stay on reviewed guides, the
 * guides index, and category hubs. Everything else fails closed: the deck
 * builder, thin and account pages, the method page, shared decks, and unknown
 * routes. Unreviewed guides are noindex, so they are excluded even if the MDX
 * still contains an ad component. Auto ads are never enabled.
 */
export function pageAllowsAds(pathname: string): boolean {
  const path = (pathname.split("?")[0] || "/").replace(/\/+$/, "") || "/";
  if (path === "/blog") return true;
  const slug = path.match(/^\/blog\/([^/]+)$/)?.[1];
  if (!slug) return false;
  if (isCategory(slug)) return true;
  // No published post: 404, archived, draft, or still scheduled. Fail closed.
  const post = getPost(slug);
  if (!post) return false;
  return post.reviewed;
}
