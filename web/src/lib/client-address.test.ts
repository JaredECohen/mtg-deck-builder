import assert from "node:assert/strict";
import test from "node:test";

import { trustedClientAddress } from "./client-address";

function headers(values: Record<string, string>): { get(name: string): string | null } {
  const lower = new Map(Object.entries(values).map(([key, value]) => [key.toLowerCase(), value]));
  return { get: (name) => lower.get(name.toLowerCase()) ?? null };
}

test("client address ignores a browser-supplied X-Forwarded-For", () => {
  assert.equal(
    trustedClientAddress(headers({ "x-forwarded-for": "203.0.113.7, 10.0.0.1" })),
    null
  );
  assert.equal(
    trustedClientAddress(
      headers({
        "x-forwarded-for": "198.51.100.9",
        "x-real-ip": "203.0.113.7",
        "x-vercel-forwarded-for": "192.0.2.20, 10.0.0.1"
      })
    ),
    "192.0.2.20"
  );
});

test("x-real-ip is used only when the platform header is absent", () => {
  assert.equal(trustedClientAddress(headers({ "x-real-ip": "203.0.113.8" })), "203.0.113.8");
  assert.equal(trustedClientAddress(headers({ "x-real-ip": "not an ip" })), null);
  assert.equal(trustedClientAddress(headers({})), null);
});
