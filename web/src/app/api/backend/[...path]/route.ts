// Same-origin proxy to the FastAPI backend.
//
// The browser talks only to /api/backend/*. This handler forwards the request
// to API_BASE and adds the X-API-Key header from the server-only MTG_API_KEY
// env var, so the key never ships in the client bundle. Cookies and the Host
// header are not forwarded; status, content type and body come back as-is.

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

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // The backend's per-client rate limit only trusts this when configured to.
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) headers.set("x-forwarded-for", forwardedFor);
  const apiKey = process.env.MTG_API_KEY;
  if (apiKey) headers.set("x-api-key", apiKey);

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
