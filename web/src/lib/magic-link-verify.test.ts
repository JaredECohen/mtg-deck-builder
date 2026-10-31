import assert from "node:assert/strict";
import test from "node:test";

import { consumeVerifyPost, renderVerifyGet } from "./magic-link-verify";

const TOKEN = "a".repeat(40);
const PREAUTH = "b".repeat(40);
const SESSION = "c".repeat(40);

function formRequest(cookie?: string): Request {
  const headers = new Headers({ "content-type": "application/x-www-form-urlencoded" });
  if (cookie) headers.set("cookie", cookie);
  return new Request("https://mtgdecklab.app/auth/verify", {
    method: "POST",
    headers,
    body: new URLSearchParams({ token: TOKEN })
  });
}

test("GET never consumes the magic link, even when a scanner repeats it", async () => {
  const calls: string[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return new Response("consumed");
  }) as typeof fetch;
  try {
    for (let i = 0; i < 3; i += 1) {
      const response = renderVerifyGet(new Request(`https://mtgdecklab.app/auth/verify?token=${TOKEN}`));
      assert.equal(response.status, 200);
      const html = await response.text();
      assert.match(html, /<button type="submit">Sign in<\/button>/);
      assert.match(html, /method="post"/);
      assert.match(html, new RegExp(`value="${TOKEN}"`));
      assert.doesNotMatch(html, /<script/i);
      assert.doesNotMatch(html, /http-equiv="refresh"/i);
      assert.equal(response.headers.get("referrer-policy"), "no-referrer");
    }
    assert.deepEqual(calls, []);
  } finally {
    globalThis.fetch = original;
  }
});

test("GET with a bad token does not call the API", () => {
  const response = renderVerifyGet(new Request("https://mtgdecklab.app/auth/verify?token=short"));
  assert.equal(response.status, 303);
  assert.match(response.headers.get("location") ?? "", /\/signin\?error=invalid$/);
});

test("POST without the preauth cookie fails and does not consume the token", async () => {
  let calls = 0;
  const fetchImpl = (async () => {
    calls += 1;
    return Response.json({ session_token: SESSION });
  }) as typeof fetch;
  const response = await consumeVerifyPost(formRequest(), fetchImpl);
  assert.equal(calls, 0);
  const html = await response.text();
  assert.match(html, /different browser/);
  assert.match(html, /Request a new link/);
  assert.equal(response.headers.get("set-cookie"), null);
});

test("POST with the wrong preauth cookie fails and leaves the token usable", async () => {
  const seen: { preauth?: string; token?: string }[] = [];
  const fetchImpl = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    seen.push(JSON.parse(String(init?.body)) as { preauth?: string; token?: string });
    return Response.json(
      { detail: { code: "preauth_mismatch", message: "other device" } },
      { status: 400 }
    );
  }) as typeof fetch;
  const response = await consumeVerifyPost(formRequest(`decklab_preauth=${"d".repeat(40)}`), fetchImpl);
  assert.equal(seen.length, 1);
  assert.equal(seen[0]?.token, TOKEN);
  assert.notEqual(seen[0]?.preauth, PREAUTH);
  const html = await response.text();
  assert.match(html, /different browser/);
  const cookies = response.headers.getSetCookie?.() ?? [];
  assert.equal(cookies.some((cookie) => cookie.startsWith("decklab_session=")), false);
});

test("POST with the matching cookie consumes the link and rotates onto a new session", async () => {
  const seen: { preauth?: string; token?: string; previous_session?: string }[] = [];
  const fetchImpl = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    seen.push(JSON.parse(String(init?.body)) as { preauth?: string; token?: string; previous_session?: string });
    return Response.json({ session_token: SESSION, user: { id: "u", email: "a@b.co" } });
  }) as typeof fetch;
  const response = await consumeVerifyPost(
    formRequest(`decklab_preauth=${PREAUTH}; decklab_session=${"e".repeat(40)}`),
    fetchImpl
  );
  assert.equal(response.status, 303);
  assert.match(response.headers.get("location") ?? "", /\/library$/);
  assert.deepEqual(seen, [{ token: TOKEN, preauth: PREAUTH, previous_session: "e".repeat(40) }]);
  const cookies = response.headers.getSetCookie();
  assert.equal(cookies.some((cookie) => cookie.includes(`decklab_session=${SESSION}`) && /HttpOnly/i.test(cookie)), true);
  assert.equal(cookies.some((cookie) => /decklab_preauth=;/.test(cookie) || /decklab_preauth=/.test(cookie) && /Max-Age=0/i.test(cookie)), true);
});
