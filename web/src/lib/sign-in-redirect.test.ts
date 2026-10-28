import assert from "node:assert/strict";
import test from "node:test";

import { signInPathForStatus } from "./sign-in-redirect";

test("an expired session is sent to sign in again", () => {
  assert.equal(signInPathForStatus(401, "Sign in required."), "/signin?error=expired");
  assert.equal(signInPathForStatus(401, "invalid or missing API key"), null);
  assert.equal(signInPathForStatus(403, "Sign in required."), null);
});
