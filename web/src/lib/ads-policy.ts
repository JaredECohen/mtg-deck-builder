import { getPost, isCategory } from "@/lib/blog";

/** Routes that are noindex and must not load an ad slot or the AdSense script. */
const NO_ADS_PATHS = new Set(["/signin", "/library", "/auth/verify"]);

/**
 * True when this path may load AdSense. Unreviewed guides are noindex, so
 * they are excluded even if the MDX still contains an ad component.
 */
export function pageAllowsAds(pathname: string): boolean {
  const path = (pathname.split("?")[0] || "/").replace(/\/+$/, "") || "/";
  if (NO_ADS_PATHS.has(path)) return false;
  const slug = path.match(/^\/blog\/([^/]+)$/)?.[1];
  if (!slug) return true;
  if (isCategory(slug)) return true;
  // No published post: 404, archived, draft, or still scheduled. Fail closed.
  const post = getPost(slug);
  if (!post) return false;
  return post.reviewed;
}
