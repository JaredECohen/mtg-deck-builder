import { ADSENSE_CLIENT } from "@/lib/ads";

/**
 * Opt this page into AdSense. The script is in the server HTML (AdSense
 * verification reads the raw response). The marker lets the shared footer
 * show its slot without the root layout reading the request.
 * Pages that do not render this stay ad-free.
 */
export function EnableAds() {
  if (!ADSENSE_CLIENT) return null;
  return (
    <>
      <script
        async
        crossOrigin="anonymous"
        src={`https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${ADSENSE_CLIENT}`}
      />
      <span hidden data-ads="on" />
    </>
  );
}
