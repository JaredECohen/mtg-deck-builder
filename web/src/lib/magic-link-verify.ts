import { NextResponse } from "next/server";

import {
  PREAUTH_COOKIE,
  SESSION_COOKIE,
  apiBase,
  apiKeyHeaders,
  isOpaqueToken,
  preauthCookie,
  readCookie,
  redirectURL,
  sessionCookie
} from "./session-cookie";

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function page(title: string, inner: string): Response {
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>${escapeHtml(title)} | MTG Deck Lab</title>
<style>
  body { margin: 0; min-height: 100vh; background: #0c1118; color: #edf3fb;
    font-family: Georgia, "Times New Roman", serif; }
  main { max-width: 36rem; margin: 0 auto; padding: 3rem 1.25rem; }
  a { color: #38bdf8; }
  button { font: inherit; background: #f97316; color: #0c1118; border: 0;
    border-radius: 999px; padding: 0.65rem 1.15rem; cursor: pointer; }
  p { line-height: 1.5; }
</style>
</head>
<body>
<main>
${inner}
</main>
</body>
</html>`;
  return new Response(html, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "referrer-policy": "no-referrer",
      "x-frame-options": "DENY",
      "x-robots-tag": "noindex",
      "content-security-policy":
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    }
  });
}

function confirmPage(token: string): Response {
  return page(
    "Sign in",
    `<h1>Sign in</h1>
<p>This link signs you in only after you press the button, and only in the browser where you requested it.</p>
<form method="post" action="/auth/verify">
  <input type="hidden" name="token" value="${escapeHtml(token)}">
  <button type="submit">Sign in</button>
</form>
<p><a href="/signin">Request a new link</a> if this one has expired.</p>`
  );
}

function otherDevicePage(): Response {
  return page(
    "Request a new link",
    `<h1>Request a new link</h1>
<p>This sign-in link was requested in a different browser. Open it in the browser where you asked for the link, or request a new link on this device.</p>
<p><a href="/signin">Request a new link</a></p>`
  );
}

/** GET renders the confirm page and does not call the API, so it cannot consume the link. */
export function renderVerifyGet(request: Request): Response {
  const token = new URL(request.url).searchParams.get("token") ?? "";
  if (!isOpaqueToken(token)) {
    return NextResponse.redirect(redirectURL(request, "/signin?error=invalid"), 303);
  }
  return confirmPage(token);
}

async function postedToken(request: Request): Promise<string> {
  const type = request.headers.get("content-type") ?? "";
  if (type.includes("application/json")) {
    const body = (await request.json().catch(() => null)) as { token?: unknown } | null;
    return typeof body?.token === "string" ? body.token : "";
  }
  const text = await request.text();
  return new URLSearchParams(text).get("token") ?? "";
}

/**
 * POST is the only step that consumes the magic link. The pre-auth cookie must
 * match the one set when this browser requested the link.
 */
export async function consumeVerifyPost(request: Request, fetchImpl: typeof fetch = globalThis.fetch): Promise<Response> {
  let token = await postedToken(request);
  if (!token) token = new URL(request.url).searchParams.get("token") ?? "";
  if (!isOpaqueToken(token)) {
    return NextResponse.redirect(redirectURL(request, "/signin?error=invalid"), 303);
  }
  const preauth = readCookie(request, PREAUTH_COOKIE);
  if (!isOpaqueToken(preauth)) return otherDevicePage();

  const previous = readCookie(request, SESSION_COOKIE);
  const payload: { token: string; preauth: string; previous_session?: string } = { token, preauth };
  if (isOpaqueToken(previous)) payload.previous_session = previous;

  let upstream: Response;
  try {
    upstream = await fetchImpl(`${apiBase()}/v1/auth/verify`, {
      method: "POST",
      headers: apiKeyHeaders({ "content-type": "application/json" }),
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(8_000)
    });
  } catch {
    return NextResponse.redirect(redirectURL(request, "/signin?error=invalid"), 303);
  }

  const body = (await upstream.json().catch(() => null)) as {
    session_token?: unknown;
    detail?: { code?: unknown } | string;
  } | null;
  const detail = body?.detail;
  if (detail && typeof detail === "object" && detail.code === "preauth_mismatch") {
    return otherDevicePage();
  }
  const sessionToken = typeof body?.session_token === "string" ? body.session_token : null;
  if (!upstream.ok || !isOpaqueToken(sessionToken)) {
    return NextResponse.redirect(redirectURL(request, "/signin?error=invalid"), 303);
  }

  const response = NextResponse.redirect(redirectURL(request, "/library"), 303);
  response.cookies.set(SESSION_COOKIE, sessionToken, sessionCookie());
  response.cookies.set(PREAUTH_COOKIE, "", preauthCookie(0));
  return response;
}
