import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { SESSION_COOKIE, apiBase, apiKeyHeaders, redirectURL, sessionCookie } from "@/lib/session-cookie";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (session) {
    try {
      await fetch(`${apiBase()}/v1/auth/logout`, {
        method: "POST",
        headers: apiKeyHeaders({ "x-user-session": session }),
        cache: "no-store",
        signal: AbortSignal.timeout(8_000)
      });
    } catch {
      // The cookie is cleared either way, so a dead API still signs the browser out.
    }
  }
  const response = NextResponse.redirect(redirectURL(request, "/"), 303);
  response.cookies.set(SESSION_COOKIE, "", sessionCookie(0));
  return response;
}
