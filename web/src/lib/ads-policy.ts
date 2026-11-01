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
  if (!slug || isCategory(slug)) return true;
  const post = getPost(slug);
  if (!post) return true;
  return post.reviewed;
}
