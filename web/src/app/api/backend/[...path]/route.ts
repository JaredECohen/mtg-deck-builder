// Same-origin proxy to the FastAPI backend.
//
// The browser talks only to /api/backend/*. This handler forwards the request
// to API_BASE and adds the X-API-Key header from the server-only MTG_API_KEY
// env var, so the key never ships in the client bundle. The raw Cookie and
// Host headers are not forwarded. A decklab_session cookie, when present, is
// sent as X-User-Session so a signed-in library stays on the API without
// putting the session token in JavaScript. Sign-in itself is not proxied:
// /v1/auth/* is rejected here so a magic-link or session token can't come
// back through this route. Listing or editing a library needs that session
// (see requiresSession). Status, content type and body come back as-is.

import { NextResponse } from "next/server";

import { decodedApiPath, isAuthPath, requiresSession } from "@/lib/backend-proxy-policy";
import { socketAddressOf, trustedClientAddress } from "@/lib/client-address";
import { SESSION_COOKIE, sessionCookie } from "@/lib/session-cookie";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const PREFIX = "/api/backend";
// The backend's own body limits are far smaller (2,000-char prompts, 250-entry
// decklists, 100 KB pasted lists). This only stops a runaway upload before it
// is buffered and forwarded.
const MAX_BODY_BYTES = 1_000_000;
// Generation with LLM help can take ~30 s; leave headroom, but don't hang forever.
// Vercel stops functions at maxDuration (60 s is the Hobby ceiling). Give up
// on the API just before that so the user gets a clean error instead of a
// killed function. LLM calls are capped at 30 s server-side and the
// optimizer runs as an async job, so nothing legitimate needs longer.
export const maxDuration = 60;
const UPSTREAM_TIMEOUT_MS = 58_000;
// Only the API's public surface is reachable through the proxy.
const ALLOWED_PREFIXES = ["/v1/", "/api/health", "/api/data-status"];
const FORWARDED_REQUEST_HEADERS = ["content-type", "accept"];

function backendBase(): string {
  const base = process.env.API_BASE || process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";
  return base.replace(/\/+$/, "");
}

function errorResponse(status: number, detail: string): Response {
  return Response.json({ detail }, { status });
}

async function forward(request: Request): Promise<Response> {
  const incoming = new URL(request.url);
  // Keep the raw (still percent-encoded) path so card names containing "/" or
  // spaces reach the backend exactly as the client encoded them.
  const path = incoming.pathname.startsWith(PREFIX) ? incoming.pathname.slice(PREFIX.length) : "";
  if (!path || path.split("/").some((segment) => segment === ".." || segment === "%2e%2e" || segment === "%2E%2E")) {
    return errorResponse(400, "Invalid API path.");
  }
  if (!ALLOWED_PREFIXES.some((prefix) => path === prefix || path.startsWith(prefix))) {
    return errorResponse(404, "Not found.");
  }
  const decoded = decodedApiPath(path);
  if (decoded === null) return errorResponse(400, "Invalid API path.");
  // Auth responses can carry a session token or a debug sign-in link. Those
  // routes are served by /api/auth/*, which keeps the token in an httpOnly cookie.
  if (isAuthPath(decoded)) {
    return errorResponse(404, "Not found.");
  }
  const session = sessionToken(request);
  if (!session && requiresSession(request.method, decoded)) {
    return errorResponse(401, "Sign in required.");
  }

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // Platform client IP only. A browser-supplied X-Forwarded-For is not forwarded.
  const clientIp = trustedClientAddress(request.headers, socketAddressOf(request));
  if (clientIp) headers.set("x-forwarded-for", clientIp);
  const apiKey = process.env.MTG_API_KEY;
  if (apiKey) headers.set("x-api-key", apiKey);
  if (session) headers.set("x-user-session", session);
  const editSecret = request.headers.get("x-deck-edit-secret");
  if (editSecret && /^[A-Za-z0-9_-]{20,200}$/.test(editSecret)) {
    headers.set("x-deck-edit-secret", editSecret);
  }

  let body: ArrayBuffer | undefined;
  if (request.method !== "GET" && request.method !== "HEAD") {
    const declared = Number(request.headers.get("content-length") ?? "0");
    if (declared > MAX_BODY_BYTES) return errorResponse(413, "Request is too large.");
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) return errorResponse(413, "Request is too large.");
  }

  // Abort upstream when the browser gives up (e.g. a superseded generate) or
  // when the upstream takes too long.
  const signal = AbortSignal.any([request.signal, AbortSignal.timeout(UPSTREAM_TIMEOUT_MS)]);

  let upstream: Response;
  try {
    upstream = await fetch(`${backendBase()}${path}${incoming.search}`, {
      method: request.method,
      headers,
      body,
      signal,
      cache: "no-store",
      redirect: "manual"
    });
  } catch (error) {
    if (error instanceof Error && error.name === "TimeoutError") {
      return errorResponse(504, "The deck service took too long to respond.");
    }
    if (request.signal.aborted) return errorResponse(499, "Request cancelled.");
    return errorResponse(502, "The deck service is unreachable. Is the API running?");
  }

  if (upstream.status === 401 && session) {
    const text = await upstream.text();
    let reauth = false;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      reauth = parsed.detail === "Sign in required.";
    } catch {
      reauth = false;
    }
    const deniedHeaders = new Headers();
    const deniedType = upstream.headers.get("content-type");
    if (deniedType) deniedHeaders.set("content-type", deniedType);
    deniedHeaders.set("cache-control", "no-store");
    const denied = new NextResponse(text, { status: 401, headers: deniedHeaders });
    if (reauth) denied.cookies.set(SESSION_COOKIE, "", sessionCookie(0));
    return denied;
  }

  const responseHeaders = new Headers();
  const contentType = upstream.headers.get("content-type");
  if (contentType) responseHeaders.set("content-type", contentType);
  responseHeaders.set("cache-control", "no-store");
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export async function GET(request: Request): Promise<Response> {
  return forward(request);
}

export async function POST(request: Request): Promise<Response> {
  return forward(request);
}

export async function DELETE(request: Request): Promise<Response> {
  return forward(request);
}

export async function PATCH(request: Request): Promise<Response> {
  return forward(request);
}

function sessionToken(request: Request): string | null {
  const header = request.headers.get("cookie");
  if (!header) return null;
  for (const part of header.split(";")) {
    const trimmed = part.trim();
    const eq = trimmed.indexOf("=");
    if (eq === -1 || trimmed.slice(0, eq) !== SESSION_COOKIE) continue;
    let value = trimmed.slice(eq + 1);
    try {
      value = decodeURIComponent(value);
    } catch {
      return null;
    }
    if (/^[A-Za-z0-9_-]{20,200}$/.test(value)) return value;
  }
  return null;
}
