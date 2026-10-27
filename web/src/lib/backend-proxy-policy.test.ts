import assert from "node:assert/strict";
import test from "node:test";

import { decodedApiPath, isAuthPath, requiresSession } from "./backend-proxy-policy";

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

test("anonymous save, share, and delete by id still pass", () => {
  assert.equal(requiresSession("POST", "/v1/decks/save"), false);
  assert.equal(requiresSession("GET", "/v1/decks/shared/tok"), false);
  assert.equal(requiresSession("GET", "/v1/decks/saved/abc"), false);
  assert.equal(requiresSession("DELETE", "/v1/decks/saved/abc"), false);
  assert.equal(requiresSession("GET", "/v1/decks/public"), false);
});
