import { NextResponse } from "next/server";

import { SESSION_COOKIE, apiBase, apiKeyHeaders, redirectURL, sessionCookie } from "@/lib/session-cookie";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const token = new URL(request.url).searchParams.get("token") ?? "";
  const signIn = redirectURL(request, "/signin");
  if (!/^[A-Za-z0-9_-]{20,200}$/.test(token)) {
    signIn.searchParams.set("error", "invalid");
    return NextResponse.redirect(signIn);
  }
  let upstream: Response;
  try {
    upstream = await fetch(`${apiBase()}/v1/auth/verify`, {
      method: "POST",
      headers: apiKeyHeaders({ "content-type": "application/json" }),
      body: JSON.stringify({ token }),
      cache: "no-store",
      signal: AbortSignal.timeout(8_000)
    });
  } catch {
    signIn.searchParams.set("error", "invalid");
    return NextResponse.redirect(signIn);
  }
  const body = (await upstream.json().catch(() => null)) as { session_token?: unknown } | null;
  if (!upstream.ok || typeof body?.session_token !== "string") {
    signIn.searchParams.set("error", "invalid");
    return NextResponse.redirect(signIn);
  }
  const response = NextResponse.redirect(redirectURL(request, "/library"));
  response.cookies.set(SESSION_COOKIE, body.session_token, sessionCookie());
  return response;
}
