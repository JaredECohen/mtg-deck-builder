import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { HiddenInArticleAd, mdxComponentsForPost } from "../components/blog/mdx-components";
import { shouldRenderAdSlot } from "./ads";
import { pageAllowsAds } from "./ads-policy";
import { syncFooterAds } from "./footer-ads";

test("unreviewed and noindex routes do not allow ads", () => {
  assert.equal(pageAllowsAds("/blog/your-first-game-of-magic"), false);
  assert.equal(pageAllowsAds("/blog/should-you-play-aggro"), true);
  assert.equal(pageAllowsAds("/blog/deck-archetypes"), true);
  assert.equal(pageAllowsAds("/signin"), false);
  assert.equal(pageAllowsAds("/library"), false);
  assert.equal(pageAllowsAds("/auth/verify"), false);
  assert.equal(pageAllowsAds("/method"), false);
  assert.equal(pageAllowsAds("/method/"), false);
  assert.equal(pageAllowsAds("/"), true);
});

test("a blog slug with no published post does not allow ads", () => {
  assert.equal(pageAllowsAds("/blog/this-guide-does-not-exist"), false);
  assert.equal(pageAllowsAds("/blog/secrets-of-strixhaven-mtg-set-guide"), false);
});

test("an unreviewed post's MDX map renders no ad unit", () => {
  const components = mdxComponentsForPost(false);
  assert.equal(components.InArticleAd, HiddenInArticleAd);
  const html = renderToStaticMarkup(createElement(components.InArticleAd));
  assert.equal(html, "");
  assert.doesNotMatch(html, /adsbygoogle|data-ad-client|data-ad-slot/);
  assert.notEqual(mdxComponentsForPost(true).InArticleAd, HiddenInArticleAd);
});

test("client navigation onto an unreviewed guide drops the footer ad slot and script", () => {
  assert.equal(pageAllowsAds("/blog/your-first-game-of-magic"), false);
  const removed: string[] = [];
  const showAds = syncFooterAds({
    querySelector: () => null,
    querySelectorAll: () => [
      { remove: () => removed.push("script") },
      { remove: () => removed.push("slot") },
    ],
  });
  assert.equal(showAds, false);
  assert.deepEqual(removed, ["script", "slot"]);

  const kept = syncFooterAds({
    querySelector: (selector) => (selector === "[data-ads='on']" ? { marker: true } : null),
    querySelectorAll: () => {
      throw new Error("an opted-in page must not strip its ad script");
    },
  });
  assert.equal(kept, true);

  const footer = fs.readFileSync(
    path.join(path.dirname(fileURLToPath(import.meta.url)), "../components/site-footer.tsx"),
    "utf8",
  );
  assert.match(footer, /usePathname\(\)/);
  assert.match(footer, /\[pathname\]/);
});

test("an ad slot stays off unless the page allows it and both ids are set", () => {
  assert.equal(shouldRenderAdSlot({ allowed: false, client: "ca-pub-1234567890", slot: "1234567890" }), false);
  assert.equal(shouldRenderAdSlot({ allowed: true, client: "", slot: "1234567890" }), false);
  assert.equal(shouldRenderAdSlot({ allowed: true, client: "ca-pub-1234567890", slot: "" }), false);
  assert.equal(shouldRenderAdSlot({ allowed: true, client: "ca-pub-1234567890", slot: "1234567890" }), true);
});
