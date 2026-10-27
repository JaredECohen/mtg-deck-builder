import { cookies } from "next/headers";

import { SESSION_COOKIE, apiBase, apiKeyHeaders } from "@/lib/session-cookie";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  // 200 with a null user, not 401: every page asks this, and a 401 shows up
  // as a failed request in the browser console for signed-out visitors.
  if (!session) return Response.json({ user: null });
  try {
    const upstream = await fetch(`${apiBase()}/v1/auth/me`, {
      headers: apiKeyHeaders({ "x-user-session": session }),
      cache: "no-store",
      signal: AbortSignal.timeout(8_000)
    });
    if (!upstream.ok) return Response.json({ user: null });
    const body = (await upstream.json()) as { user?: { id?: unknown; email?: unknown } };
    const id = body.user?.id;
    const email = body.user?.email;
    if (typeof id !== "string" || typeof email !== "string") return Response.json({ user: null });
    return Response.json({ user: { id, email } });
  } catch {
    return Response.json({ user: null });
  }
}
