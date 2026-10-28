import { apiBase, apiKeyHeaders, authDebugEnabled } from "@/lib/session-cookie";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  let email = "";
  try {
    const body = (await request.json()) as { email?: unknown };
    email = typeof body?.email === "string" ? body.email : "";
  } catch {
    return Response.json({ detail: "Enter a valid email address." }, { status: 400 });
  }

  // The API limits sign-in requests per client IP. Without the visitor's address
  // every request would count against this server's IP, and 20 requests an hour
  // from anyone would lock sign-in for everybody.
  const headers = apiKeyHeaders({ "content-type": "application/json" });
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) headers.set("x-forwarded-for", forwardedFor);

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
  return Response.json(payload);
}
