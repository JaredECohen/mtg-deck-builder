import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { SESSION_COOKIE, apiBase, apiKeyHeaders, sessionCookie } from "@/lib/session-cookie";

export const dynamic = "force-dynamic";

export async function DELETE(): Promise<Response> {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return Response.json({ detail: "Sign in required." }, { status: 401 });
  let upstream: Response;
  try {
    upstream = await fetch(`${apiBase()}/v1/auth/me`, {
      method: "DELETE",
      headers: apiKeyHeaders({ "x-user-session": session }),
      cache: "no-store",
      signal: AbortSignal.timeout(8_000)
    });
  } catch {
    return Response.json({ detail: "The deck service is unreachable." }, { status: 502 });
  }
  if (!upstream.ok) return Response.json({ detail: "Could not delete the account." }, { status: upstream.status });
  const response = NextResponse.json({ deleted: true });
  response.cookies.set(SESSION_COOKIE, "", sessionCookie(0));
  return response;
}
