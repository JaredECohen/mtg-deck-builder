import assert from "node:assert/strict";
import test from "node:test";

import { trustedClientAddress } from "./client-address";

function headers(values: Record<string, string>): { get(name: string): string | null } {
  const lower = new Map(Object.entries(values).map(([key, value]) => [key.toLowerCase(), value]));
  return { get: (name) => lower.get(name.toLowerCase()) ?? null };
}

const spoofed = headers({
  "x-forwarded-for": "198.51.100.9",
  "x-real-ip": "203.0.113.7",
  "x-vercel-forwarded-for": "192.0.2.20, 10.0.0.1"
});

test("off Vercel, platform IP headers are ignored and the socket address is used", () => {
  assert.equal(trustedClientAddress(spoofed, "203.0.113.50", false), "203.0.113.50");
  assert.equal(trustedClientAddress(spoofed, null, false), null);
  assert.equal(trustedClientAddress(headers({}), "not an ip", false), null);
});

test("on Vercel, the platform header wins over the socket and a spoofed X-Forwarded-For", () => {
  assert.equal(trustedClientAddress(spoofed, "10.1.1.1", true), "192.0.2.20");
  assert.equal(
    trustedClientAddress(headers({ "x-real-ip": "203.0.113.8" }), "10.1.1.1", true),
    "203.0.113.8"
  );
  assert.equal(trustedClientAddress(headers({ "x-real-ip": "not an ip" }), null, true), null);
  assert.equal(trustedClientAddress(headers({ "x-forwarded-for": "198.51.100.9" }), null, true), null);
});
