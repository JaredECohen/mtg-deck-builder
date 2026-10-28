import assert from "node:assert/strict";
import test from "node:test";

import { PREAUTH_MAX_AGE, cookieSecure, preauthCookie, sessionCookie } from "./session-cookie";

function setNodeEnv(value: string | undefined) {
  (process.env as Record<string, string | undefined>).NODE_ENV = value;
}

test("preauth cookie is httpOnly, lax, short-lived, and secure only in production", () => {
  const previous = process.env.NODE_ENV;
  try {
    setNodeEnv("development");
    assert.equal(cookieSecure(), false);
    const dev = preauthCookie();
    assert.equal(dev.httpOnly, true);
    assert.equal(dev.secure, false);
    assert.equal(dev.sameSite, "lax");
    assert.equal(dev.path, "/auth/verify");
    assert.equal(dev.maxAge, PREAUTH_MAX_AGE);
    assert.equal(PREAUTH_MAX_AGE, 20 * 60);

    setNodeEnv("production");
    assert.equal(preauthCookie().secure, true);
    assert.equal(sessionCookie().secure, true);
    assert.equal(sessionCookie().httpOnly, true);
    assert.equal(sessionCookie().sameSite, "lax");
  } finally {
    setNodeEnv(previous);
  }
});
