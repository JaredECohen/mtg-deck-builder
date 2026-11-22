import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { POST } from "../app/api/usage/route";
import { allowUsageClient, resetUsageClientLimit, usageClientBuckets, usageClientBudget } from "./usage-client-limit";
import {
  clientUsagePayload,
  documentViewPayload,
  postUsageEvent,
  readCoarseLocation,
  scheduleDocumentView,
  shouldRecordDocumentView,
  type UsagePayload,
} from "./usage";

const COARSE =
  "We record the approximate location (country, region, city) derived from your connection when you use the app. We do not store your IP address or precise location.";
const SCRAMBLED =
  "To prevent abuse, we briefly keep a scrambled form of your connection address for rate limiting, deleted within 2 days.";

test("coarse location is the decoded vercel headers", () => {
  const headers = new Headers({
    "x-vercel-ip-country": "US",
    "x-vercel-ip-country-region": "CA",
    "x-vercel-ip-city": "S%C3%A3o%20Paulo",
  });
  assert.deepEqual(readCoarseLocation(headers), {
    country: "US",
    region: "CA",
    city: "São Paulo",
  });
});

test("missing geo headers are null", () => {
  assert.deepEqual(readCoarseLocation(new Headers()), {
    country: null,
    region: null,
    city: null,
  });
  assert.deepEqual(readCoarseLocation(new Headers({ "x-vercel-ip-country": "  " })), {
    country: null,
    region: null,
    city: null,
  });
});

test("client usage ignores geo and addresses supplied by the browser", async () => {
  const request = new Request("https://mtgdecklab.app/api/usage", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-vercel-ip-country": "DE",
      "x-vercel-ip-country-region": "BE",
      "x-vercel-ip-city": "S%C3%A3o%20Paulo",
      "x-vercel-ip-latitude": "52.52",
      "x-vercel-ip-longitude": "13.40",
      "x-vercel-ip-postal-code": "10115",
      "x-forwarded-for": "203.0.113.9",
      "x-vercel-forwarded-for": "203.0.113.9",
    },
    body: JSON.stringify({
      event: "guide_viewed",
      path: "/blog/mtg-mulligan-guide?brief=secret%20deck#notes",
      country: "US",
      region: "NY",
      city: "1.2.3.4",
      ip: "198.51.100.4",
      latitude: 52.52,
      postcode: "10115",
    }),
  });
  const payload = await clientUsagePayload(request);
  assert.deepEqual(payload, {
    event: "guide_viewed",
    path: "/blog/mtg-mulligan-guide",
    country: "DE",
    region: "BE",
    city: "São Paulo",
  });
  const encoded = JSON.stringify(payload);
  assert.equal(encoded.includes("203.0.113"), false);
  assert.equal(encoded.includes("198.51.100"), false);
  assert.equal(encoded.includes("52.52"), false);
  assert.equal(encoded.includes("10115"), false);
  assert.equal(encoded.includes("secret"), false);
  assert.equal(encoded.includes("1.2.3.4"), false);
});

test("a funnel event with no geo headers stores null location", async () => {
  const request = new Request("https://mtgdecklab.app/api/usage", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ event: "deck_shared", path: "/library?deck=token#list" }),
  });
  assert.deepEqual(await clientUsagePayload(request), {
    event: "deck_shared",
    path: "/library",
    country: null,
    region: null,
    city: null,
  });
});

test("an ip-shaped city header is dropped", async () => {
  const request = new Request("https://mtgdecklab.app/api/usage", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-vercel-ip-country": "US",
      "x-vercel-ip-city": "203.0.113.8",
      "x-vercel-ip-country-region": "2001:db8::1",
    },
    body: JSON.stringify({ event: "deck_exported", path: "/" }),
  });
  const payload = await clientUsagePayload(request);
  assert.equal(payload?.country, "US");
  assert.equal(payload?.region, null);
  assert.equal(payload?.city, null);
});

test("document views skip assets, health, and the usage endpoint", () => {
  const html = new Headers({ accept: "text/html" });
  assert.equal(shouldRecordDocumentView("GET", "/", html), true);
  assert.equal(shouldRecordDocumentView("GET", "/blog/mtg-formats-explained", html), true);
  assert.equal(shouldRecordDocumentView("GET", "/_next/static/chunk.js", html), false);
  assert.equal(shouldRecordDocumentView("GET", "/favicon.ico", html), false);
  assert.equal(shouldRecordDocumentView("GET", "/api/health", html), false);
  assert.equal(shouldRecordDocumentView("GET", "/health", html), false);
  assert.equal(shouldRecordDocumentView("GET", "/api/usage", html), false);
  assert.equal(shouldRecordDocumentView("GET", "/api/backend/v1/usage", html), false);
  assert.equal(shouldRecordDocumentView("POST", "/", html), false);
  assert.equal(shouldRecordDocumentView("GET", "/", new Headers({ accept: "application/json" })), false);
  assert.equal(shouldRecordDocumentView("GET", "/", new Headers()), false);
  assert.equal(shouldRecordDocumentView("GET", "/library", new Headers({ rsc: "1" })), false);
  assert.equal(
    shouldRecordDocumentView("GET", "/library", new Headers({ accept: "text/html", "next-router-prefetch": "1" })),
    false,
  );
});

test("an RSC flight is not recorded and a text/html document is", () => {
  const recorded: string[] = [];
  const visit = (headers: Headers) => {
    let scheduled = false;
    scheduleDocumentView(
      { method: "GET", pathname: "/library", search: "", headers },
      () => {
        scheduled = true;
      },
      async (payload) => {
        recorded.push(payload.path);
      },
    );
    return scheduled;
  };
  assert.equal(visit(new Headers({ rsc: "1", accept: "text/x-component" })), false);
  assert.equal(visit(new Headers({ rsc: "1", accept: "text/html" })), false);
  assert.equal(visit(new Headers({ accept: "text/html", "next-router-state-tree": "%5B%5D" })), false);
  assert.equal(visit(new Headers({ accept: "text/html,*/*" })), true);
  assert.deepEqual(recorded, ["/library"]);
});

test("a document view is scheduled without waiting for the write", async () => {
  const box: { scheduled: Promise<unknown> | null } = { scheduled: null };
  let observed: UsagePayload | null = null;
  let release = () => {};
  const hung = new Promise<void>((resolve) => {
    release = resolve;
  });
  scheduleDocumentView(
    {
      method: "GET",
      pathname: "/auth/verify",
      search: "?token=secret-token",
      headers: new Headers({
        accept: "text/html",
        "x-vercel-ip-country": "US",
        "x-vercel-ip-country-region": "NY",
        "x-vercel-ip-city": "New%20York",
        "x-vercel-ip-latitude": "40.7",
      }),
    },
    (promise) => {
      box.scheduled = promise;
    },
    async (payload) => {
      observed = payload;
      await hung;
    },
  );
  const scheduled = box.scheduled;
  if (!scheduled) throw new Error("page view was not scheduled");
  assert.deepEqual(observed, {
    event: "page_view",
    path: "/auth/verify",
    country: "US",
    region: "NY",
    city: "New York",
  });
  let settled = false;
  void scheduled.then(() => {
    settled = true;
  });
  await Promise.resolve();
  assert.equal(settled, false);
  release();
  await scheduled;
  assert.equal(settled, true);
  const encoded = JSON.stringify(observed);
  assert.equal(encoded.includes("secret-token"), false);
  assert.equal(encoded.includes("40.7"), false);
  const view = documentViewPayload("/d/abcDEF123456", "?utm_source=discord", new Headers());
  assert.equal(view?.path, "/d");
  assert.equal(view?.country, null);
});

test("postUsageEvent sends the secret header and skips when it is unset", async () => {
  const previousSecret = process.env.USAGE_INGEST_SECRET;
  const previousBase = process.env.API_BASE;
  const seen: { url?: string; secret?: string | null; body?: string; calls: number } = { calls: 0 };
  const fetchImpl: typeof fetch = async (input, init) => {
    seen.calls += 1;
    const headers = new Headers(init?.headers);
    seen.url = String(input);
    seen.secret = headers.get("x-usage-ingest-secret");
    seen.body = String(init?.body ?? "");
    return new Response(null, { status: 204 });
  };
  try {
    delete process.env.USAGE_INGEST_SECRET;
    await postUsageEvent(
      { event: "page_view", path: "/", country: null, region: null, city: null },
      fetchImpl,
    );
    assert.equal(seen.calls, 0);

    process.env.USAGE_INGEST_SECRET = "server-secret";
    process.env.API_BASE = "http://api.test";
    await postUsageEvent(
      { event: "page_view", path: "/privacy", country: "US", region: "CA", city: "Oakland" },
      fetchImpl,
    );
    assert.equal(seen.calls, 1);
    assert.equal(seen.url, "http://api.test/v1/usage");
    assert.equal(seen.secret, "server-secret");
    assert.equal(seen.body?.includes("server-secret"), false);
    assert.deepEqual(Object.keys(JSON.parse(seen.body ?? "{}")).sort(), [
      "city",
      "country",
      "event",
      "path",
      "region",
    ]);
  } finally {
    if (previousSecret === undefined) delete process.env.USAGE_INGEST_SECRET;
    else process.env.USAGE_INGEST_SECRET = previousSecret;
    if (previousBase === undefined) delete process.env.API_BASE;
    else process.env.API_BASE = previousBase;
  }
});

test("the usage route acknowledges and does not throw", async () => {
  const previous = process.env.USAGE_INGEST_SECRET;
  delete process.env.USAGE_INGEST_SECRET;
  try {
    const response = await POST(
      new Request("https://mtgdecklab.app/api/usage", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ event: "deck_shared", path: "/library?x=1#y", ip: "203.0.113.9" }),
      }),
    );
    assert.equal(response.status, 204);
  } finally {
    if (previous === undefined) delete process.env.USAGE_INGEST_SECRET;
    else process.env.USAGE_INGEST_SECRET = previous;
  }
});

test("the usage route limits one client in memory without keeping the address", async () => {
  const previousSecret = process.env.USAGE_INGEST_SECRET;
  const previousBase = process.env.API_BASE;
  const previousVercel = process.env.VERCEL;
  const previousLimit = usageClientBudget.limit;
  resetUsageClientLimit();
  usageClientBudget.limit = 2;
  process.env.USAGE_INGEST_SECRET = "server-secret";
  process.env.API_BASE = "http://api.test";
  process.env.VERCEL = "1";
  let calls = 0;
  const original = globalThis.fetch;
  globalThis.fetch = (async () => {
    calls += 1;
    return new Response(null, { status: 204 });
  }) as typeof fetch;
  const body = JSON.stringify({ event: "deck_shared", path: "/library" });
  const headers = {
    "content-type": "application/json",
    "x-vercel-forwarded-for": "203.0.113.40",
  };
  try {
    const first = await POST(new Request("https://mtgdecklab.app/api/usage", { method: "POST", headers, body }));
    const second = await POST(new Request("https://mtgdecklab.app/api/usage", { method: "POST", headers, body }));
    const third = await POST(new Request("https://mtgdecklab.app/api/usage", { method: "POST", headers, body }));
    assert.equal(first.status, 204);
    assert.equal(second.status, 204);
    assert.equal(third.status, 429);
    assert.equal(calls, 2);
    const buckets = usageClientBuckets().join(" ");
    assert.equal(buckets.includes("203.0.113.40"), false);
    assert.equal(buckets.length > 0, true);
  } finally {
    globalThis.fetch = original;
    resetUsageClientLimit();
    usageClientBudget.limit = previousLimit;
    if (previousSecret === undefined) delete process.env.USAGE_INGEST_SECRET;
    else process.env.USAGE_INGEST_SECRET = previousSecret;
    if (previousBase === undefined) delete process.env.API_BASE;
    else process.env.API_BASE = previousBase;
    if (previousVercel === undefined) delete process.env.VERCEL;
    else process.env.VERCEL = previousVercel;
  }
});

test("idle usage buckets are swept and a full map evicts the oldest", () => {
  resetUsageClientLimit();
  const previous = { ...usageClientBudget };
  usageClientBudget.limit = 5;
  usageClientBudget.windowMs = 1000;
  usageClientBudget.maxBuckets = 2;
  try {
    assert.equal(allowUsageClient("a", 0), true);
    assert.equal(allowUsageClient("b", 0), true);
    assert.equal(allowUsageClient("c", 1001), true);
    assert.deepEqual(usageClientBuckets(), ["c"]);

    resetUsageClientLimit();
    assert.equal(allowUsageClient("a", 5000), true);
    assert.equal(allowUsageClient("b", 5000), true);
    assert.equal(allowUsageClient("c", 5000), true);
    assert.deepEqual(usageClientBuckets(), ["b", "c"]);
    assert.equal(usageClientBuckets().includes("a"), false);
  } finally {
    resetUsageClientLimit();
    usageClientBudget.limit = previous.limit;
    usageClientBudget.windowMs = previous.windowMs;
    usageClientBudget.maxBuckets = previous.maxBuckets;
  }
});

test("the privacy page states coarse location and the two-day rate limit", () => {
  const source = fs.readFileSync(fileURLToPath(new URL("../app/privacy/page.tsx", import.meta.url)), "utf8");
  assert.equal(source.includes(COARSE), true);
  assert.equal(source.includes(SCRAMBLED), true);
  assert.match(source, /\{COARSE_LOCATION\} \{RATE_LIMIT_RETENTION\}/);
  assert.match(source, /November 22, 2026/);
  assert.ok(source.indexOf(COARSE) < source.indexOf(SCRAMBLED));
});
