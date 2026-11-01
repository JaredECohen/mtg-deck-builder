const AD_OPT_IN = "[data-ads='on']";
const AD_LEFTOVERS = 'script[src*="adsbygoogle"], ins.adsbygoogle';

type AdNode = { remove: () => void };

export type AdDom = {
  querySelector: (selector: string) => unknown;
  querySelectorAll: (selector: string) => Iterable<AdNode>;
};

/**
 * Footer ads follow the page currently on screen. No opt-in marker means the
 * slot stays off, and any AdSense script or slot left from the previous page
 * is removed. The layout does not remount on client navigation, so callers
 * must run this again whenever the path changes.
 */
export function syncFooterAds(root: AdDom): boolean {
  const showAds = root.querySelector(AD_OPT_IN) != null;
  if (!showAds) {
    for (const node of root.querySelectorAll(AD_LEFTOVERS)) node.remove();
  }
  return showAds;
}
