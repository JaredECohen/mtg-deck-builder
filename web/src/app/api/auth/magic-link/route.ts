import { randomBytes } from "node:crypto";

import { NextResponse } from "next/server";

import { socketAddressOf, trustedClientAddress } from "@/lib/client-address";
import { PREAUTH_COOKIE, apiBase, apiKeyHeaders, authDebugEnabled, preauthCookie } from "@/lib/session-cookie";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  let email = "";
  try {
    const body = (await request.json()) as { email?: unknown };
    email = typeof body?.email === "string" ? body.email : "";
  } catch {
    return Response.json({ detail: "Enter a valid email address." }, { status: 400 });
  }

  // Bind the link to this browser. The value is an httpOnly cookie, not part of
  // the JSON the page can read, and it is not put in the email.
  const preauth = randomBytes(32).toString("base64url");
  const headers = apiKeyHeaders({ "content-type": "application/json", "x-preauth": preauth });
  // The API limits sign-in requests per client IP. Report the platform's view
  // of that IP. Never forward the browser's X-Forwarded-For: the client can set it.
  const clientIp = trustedClientAddress(request.headers, socketAddressOf(request));
  if (clientIp) headers.set("x-forwarded-for", clientIp);

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBase()}/v1/auth/magic-link`, {
      method: "POST",
      headers,
      body: JSON.stringify({ email }),
      cache: "no-store",
      signal: AbortSignal.timeout(15_000)
    });
  } catch {
    return Response.json({ detail: "The deck service is unreachable." }, { status: 502 });
  }

  if (upstream.status === 401 || upstream.status === 403) {
    return Response.json({ detail: "Sign-in is unavailable right now." }, { status: 503 });
  }
  const body = (await upstream.json().catch(() => null)) as { ok?: boolean; debug_url?: unknown; detail?: unknown } | null;
  if (!upstream.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : "Could not send the sign-in link.";
    return Response.json({ detail }, { status: upstream.status });
  }
  const payload: { ok: true; debug_url?: string } = { ok: true };
  if (authDebugEnabled() && typeof body?.debug_url === "string") payload.debug_url = body.debug_url;
  const response = NextResponse.json(payload);
  response.cookies.set(PREAUTH_COOKIE, preauth, preauthCookie());
  return response;
}
