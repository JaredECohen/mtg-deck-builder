import { getPost, isCategory } from "@/lib/blog";

/**
 * Routes that must not load an ad slot or the AdSense script: the deck
 * builder, thin pages, account pages, and the method page. Anything that is
 * not the guides index, a category hub, or a reviewed guide also fails closed
 * (shared decks, unknown routes). Auto ads are never enabled.
 */
const NO_ADS_PATHS = new Set([
  "/",
  "/about",
  "/contact",
  "/privacy",
  "/signin",
  "/library",
  "/auth/verify",
  "/method",
]);

/**
 * True when this path may load AdSense. Ads stay on reviewed guides, the
 * guides index, and category hubs. Unreviewed guides are noindex, so they
 * are excluded even if the MDX still contains an ad component.
 */
export function pageAllowsAds(pathname: string): boolean {
  const path = (pathname.split("?")[0] || "/").replace(/\/+$/, "") || "/";
  if (path === "/blog") return true;
  if (NO_ADS_PATHS.has(path)) return false;
  const slug = path.match(/^\/blog\/([^/]+)$/)?.[1];
  if (!slug) return false;
  if (isCategory(slug)) return true;
  // No published post: 404, archived, draft, or still scheduled. Fail closed.
  const post = getPost(slug);
  if (!post) return false;
  return post.reviewed;
}
