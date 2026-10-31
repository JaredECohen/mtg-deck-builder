import assert from "node:assert/strict";
import test from "node:test";

import { accountFromMePayload } from "./account-payload";

test("a rejected session cookie asks the page to sign in again", () => {
  assert.equal(accountFromMePayload({ user: null, reauth: true }), "reauth");
  assert.deepEqual(accountFromMePayload({ user: { id: "u1", email: "a@b.co" } }), { id: "u1", email: "a@b.co" });
  assert.equal(accountFromMePayload({ user: null }), null);
  assert.equal(accountFromMePayload(null), null);
});
