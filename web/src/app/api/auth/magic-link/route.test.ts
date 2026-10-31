import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { POST } from "./route";

function setNodeEnv(value: string | undefined) {
  (process.env as Record<string, string | undefined>).NODE_ENV = value;
}

function setVercel(value: string | undefined) {
  if (value === undefined) delete process.env.VERCEL;
  else process.env.VERCEL = value;
}

describe("magic-link client address", { concurrency: 1 }, () => {
test("magic-link sets the preauth cookie and does not trust X-Forwarded-For", async () => {
  const seen: { forwarded?: string | null; preauth?: string | null }[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    seen.push({
      forwarded: headers.get("x-forwarded-for"),
      preauth: headers.get("x-preauth")
    });
    return Response.json({ ok: true, debug_url: "https://example.test/auth/verify?token=secret" });
  }) as typeof fetch;
  const previousDebug = process.env.MTG_AUTH_DEBUG;
  const previousNode = process.env.NODE_ENV;
  const previousVercel = process.env.VERCEL;
  try {
    process.env.MTG_AUTH_DEBUG = "1";
    setNodeEnv("development");
    setVercel("1");
    const response = await POST(new Request("https://mtgdecklab.app/api/auth/magic-link", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-forwarded-for": "198.51.100.9, 10.0.0.1",
        "x-vercel-forwarded-for": "203.0.113.7, 10.0.0.2"
      },
      body: JSON.stringify({ email: "pilot@example.com" })
    }));
    assert.equal(response.status, 200);
    const payload = await response.json() as { ok?: boolean; debug_url?: string };
    assert.equal(payload.ok, true);
    assert.equal(typeof payload.debug_url, "string");
    assert.equal(seen.length, 1);
    assert.equal(seen[0]?.forwarded, "203.0.113.7");
    const preauth = seen[0]?.preauth ?? "";
    assert.match(preauth, /^[A-Za-z0-9_-]{20,200}$/);
    assert.equal(JSON.stringify(payload).includes(preauth), false);
    const cookies = response.headers.getSetCookie();
    const cookie = cookies.find((item) => item.startsWith("decklab_preauth="));
    assert.ok(cookie);
    assert.match(cookie, new RegExp(`decklab_preauth=${preauth}`));
    assert.match(cookie, /HttpOnly/i);
    assert.match(cookie, /SameSite=Lax/i);
    assert.match(cookie, /Path=\/auth\/verify/);
    assert.doesNotMatch(cookie, /Secure/i);
  } finally {
    globalThis.fetch = original;
    process.env.MTG_AUTH_DEBUG = previousDebug;
    setNodeEnv(previousNode);
    setVercel(previousVercel);
  }
});

test("off Vercel the route forwards the socket address and ignores platform IP headers", async () => {
  let forwarded: string | null = "unset";
  const original = globalThis.fetch;
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    forwarded = new Headers(init?.headers).get("x-forwarded-for");
    return Response.json({ ok: true });
  }) as typeof fetch;
  const previousVercel = process.env.VERCEL;
  try {
    setVercel(undefined);
    const request = new Request("https://mtgdecklab.app/api/auth/magic-link", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-forwarded-for": "198.51.100.9",
        "x-real-ip": "203.0.113.7",
        "x-vercel-forwarded-for": "192.0.2.20"
      },
      body: JSON.stringify({ email: "pilot@example.com" })
    });
    Object.defineProperty(request, "socket", { value: { remoteAddress: "203.0.113.50" } });
    const response = await POST(request);
    assert.equal(response.status, 200);
    assert.equal(forwarded, "203.0.113.50");
  } finally {
    globalThis.fetch = original;
    setVercel(previousVercel);
  }
});
});
