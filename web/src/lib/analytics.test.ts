import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { CATEGORIES } from "./blog";
import {
  ANALYTICS_EVENT_PROPS,
  GUIDE_CATEGORIES,
  redactAnalyticsUrl,
  sanitizeEvent,
  setAnalyticsTransport,
  trackDeckExported,
  trackDeckGenerated,
  trackDeckRefined,
  trackDeckPageViewed,
  trackDeckShared,
  trackGuideViewed,
  trackTcgplayerCartClicked,
  type AnalyticsProps,
} from "./analytics";

const PROMPT = "Build a cheap Izzet deck for game night, email me at ada@example.com";

afterEach(() => {
  setAnalyticsTransport(null);
});

test("every funnel event has at most two properties", () => {
  for (const [name, keys] of Object.entries(ANALYTICS_EVENT_PROPS)) {
    assert.ok(keys.length >= 1 && keys.length <= 2, name);
  }
  assert.deepEqual(Object.keys(ANALYTICS_EVENT_PROPS), [
    "deck_generated",
    "deck_refined",
    "deck_exported",
    "deck_shared",
    "deck_page_viewed",
    "tcgplayer_cart_clicked",
    "guide_viewed",
  ]);
});

test("guide categories match the published guide hubs", () => {
  assert.deepEqual([...GUIDE_CATEGORIES].sort(), Object.keys(CATEGORIES).sort());
});

test("sanitizeEvent drops prompts, titles, and tokens", () => {
  const event = sanitizeEvent("deck_generated", {
    format: "modern",
    source: "new",
    prompt: PROMPT,
    brief: PROMPT,
    email: "ada@example.com",
    title: "Ada's secret deck",
    token: "share-token-value",
    notes: PROMPT,
    deck: PROMPT,
  });
  assert.deepEqual(event, {
    name: "deck_generated",
    props: { format: "modern", source: "new" },
  });
  const encoded = JSON.stringify(event);
  assert.equal(encoded.includes("ada@"), false);
  assert.equal(encoded.includes("Izzet"), false);
  assert.equal(encoded.includes("share-token"), false);
});

test("a prompt stuffed into a property drops the event", () => {
  assert.equal(sanitizeEvent("deck_refined", { format: PROMPT }), null);
  assert.equal(sanitizeEvent("deck_generated", { format: "modern", source: "please build this" }), null);
  assert.equal(sanitizeEvent("guide_viewed", { slug: "my deck list", category: "strategy" }), null);
  assert.equal(sanitizeEvent("not_an_event", { format: "modern" }), null);
});

test("deck_exported accepts only arena, moxfield, and archidekt", () => {
  for (const target of ["arena", "moxfield", "archidekt"]) {
    assert.deepEqual(sanitizeEvent("deck_exported", { target, format: "commander" }), {
      name: "deck_exported",
      props: { target, format: "commander" },
    });
  }
  assert.equal(sanitizeEvent("deck_exported", { target: "plain", format: "modern" }), null);
  assert.equal(sanitizeEvent("deck_exported", { target: "csv", format: "legacy" }), null);
  assert.equal(sanitizeEvent("deck_exported", { target: "arena", format: "pauper" }), null);
});

test("track helpers send the sanitized payload and nothing else", () => {
  const seen: { name: string; props: AnalyticsProps }[] = [];
  setAnalyticsTransport((name, props) => {
    seen.push({ name, props });
  });

  trackDeckGenerated("commander", "alternative");
  trackDeckGenerated("Commander", "new");
  trackDeckRefined("pioneer");
  trackDeckExported("moxfield", "standard");
  trackDeckExported("plain", "standard");
  trackDeckExported("csv", "standard");
  trackDeckShared("legacy");
  trackDeckPageViewed("commander");
  trackDeckPageViewed("Ada's deck");
  trackTcgplayerCartClicked("modern");
  trackGuideViewed("mtg-mulligan-guide", "strategy");
  trackGuideViewed("../etc/passwd", "strategy");

  assert.deepEqual(seen, [
    { name: "deck_generated", props: { format: "commander", source: "alternative" } },
    { name: "deck_refined", props: { format: "pioneer" } },
    { name: "deck_exported", props: { target: "moxfield", format: "standard" } },
    { name: "deck_shared", props: { format: "legacy" } },
    { name: "deck_page_viewed", props: { format: "commander" } },
    { name: "tcgplayer_cart_clicked", props: { format: "modern" } },
    { name: "guide_viewed", props: { slug: "mtg-mulligan-guide", category: "strategy" } },
  ]);
});

test("page URLs lose brief text and share tokens", () => {
  const messy =
    "https://mtgdecklab.app/?format=commander&brief=" +
    encodeURIComponent(PROMPT) +
    "&deck=abcDEF123456&utm_source=newsletter";
  const redacted = redactAnalyticsUrl(messy);
  assert.ok(redacted);
  const url = new URL(redacted);
  assert.equal(url.origin, "https://mtgdecklab.app");
  assert.equal(url.searchParams.get("format"), "commander");
  assert.equal(url.searchParams.get("utm_source"), "newsletter");
  assert.equal(url.searchParams.has("brief"), false);
  assert.equal(url.searchParams.has("deck"), false);
  assert.equal(redacted.includes("ada@"), false);
  assert.equal(redacted.includes("abcDEF"), false);

  const shared = redactAnalyticsUrl("https://mtgdecklab.app/d/abcDEF123456?utm_source=discord");
  assert.equal(shared, "https://mtgdecklab.app/d?utm_source=discord");
  assert.equal(redactAnalyticsUrl("/d/abcDEF123456"), "/d");
  assert.equal(redactAnalyticsUrl("/d/abcDEF123456?deck=abcDEF123456"), "/d");
});

test("page URLs keep a normal guide path and a safe format hash link", () => {
  assert.equal(
    redactAnalyticsUrl("https://mtgdecklab.app/blog/mtg-formats-explained"),
    "https://mtgdecklab.app/blog/mtg-formats-explained"
  );
  assert.equal(redactAnalyticsUrl("/?format=modern#builder"), "/?format=modern#builder");
  assert.equal(redactAnalyticsUrl("/?format=not-a-format&brief=hello"), "/");
  assert.equal(redactAnalyticsUrl("https://mtgdecklab.app/?utm_campaign=" + "a".repeat(200)), "https://mtgdecklab.app/");
});
