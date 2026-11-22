import assert from "node:assert/strict";
import test from "node:test";

import { GET, POST } from "../app/api/backend/[...path]/route";
import { decodedApiPath, isAuthPath, isUsageIngestPath, requiresSession } from "./backend-proxy-policy";

test("auth routes are refused even when percent-encoded", () => {
  for (const raw of ["/v1/auth", "/v1/auth/verify", "/v1/%61uth/verify", "/v1/auth%2Fme"]) {
    const decoded = decodedApiPath(raw);
    assert.ok(decoded !== null && isAuthPath(decoded), raw);
  }
  assert.equal(isAuthPath("/v1/authors"), false);
  assert.equal(decodedApiPath("/v1/%E0%A4%A"), null);
});

test("listing and editing a library need a session", () => {
  assert.equal(requiresSession("GET", "/v1/decks/history"), true);
  assert.equal(requiresSession("GET", decodedApiPath("/v1/decks/%68istory")!), true);
  assert.equal(requiresSession("PATCH", "/v1/decks/saved/abc"), true);
});

test("the usage ingest path is blocked, including percent-encoding", () => {
  for (const raw of ["/v1/usage", "/v1/usage/events", "/v1/USAGE", "/v1/%75sage", "/v1/usage%2Fextra"]) {
    const decoded = decodedApiPath(raw);
    assert.ok(decoded !== null && isUsageIngestPath(decoded), raw);
  }
  assert.equal(isUsageIngestPath("/v1/users"), false);
  assert.equal(isUsageIngestPath("/v1/decks/generate"), false);
});

test("the browser proxy does not forward the usage ingest endpoint", async () => {
  const original = globalThis.fetch;
  let called = false;
  globalThis.fetch = (async () => {
    called = true;
    return new Response("nope");
  }) as typeof fetch;
  try {
    for (const target of [
      "https://mtgdecklab.app/api/backend/v1/usage",
      "https://mtgdecklab.app/api/backend/v1/%75sage",
    ]) {
      called = false;
      const init = {
        method: "POST",
        headers: { "content-type": "application/json", "x-usage-ingest-secret": "guess" },
        body: JSON.stringify({ event: "page_view", path: "/", country: "US", ip: "203.0.113.9" }),
      };
      const posted = await POST(new Request(target, init));
      assert.equal(posted.status, 404, target);
      const fetched = await GET(new Request(target));
      assert.equal(fetched.status, 404, target);
      assert.equal(called, false, target);
    }
  } finally {
    globalThis.fetch = original;
  }
});

test("anonymous save, share, and delete by id still pass", () => {
  assert.equal(requiresSession("POST", "/v1/decks/save"), false);
  assert.equal(requiresSession("GET", "/v1/decks/shared/tok"), false);
  assert.equal(requiresSession("GET", "/v1/decks/saved/abc"), false);
  assert.equal(requiresSession("DELETE", "/v1/decks/saved/abc"), false);
  assert.equal(requiresSession("GET", "/v1/decks/public"), false);
});
