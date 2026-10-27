export const SESSION_COOKIE = "decklab_session";
const THIRTY_DAYS = 60 * 60 * 24 * 30;

export function sessionCookie(maxAge = THIRTY_DAYS) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge
  };
}

export function apiBase(): string {
  return (process.env.API_BASE || process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000").replace(/\/+$/, "");
}

export function apiKeyHeaders(extra?: Record<string, string>): Headers {
  const headers = new Headers(extra);
  const key = process.env.MTG_API_KEY;
  if (key) headers.set("x-api-key", key);
  return headers;
}

export function authDebugEnabled(): boolean {
  return ["1", "true", "yes"].includes((process.env.MTG_AUTH_DEBUG ?? "").toLowerCase());
}

/** Absolute URL for a redirect that stays on the host the browser used.
 * Next sometimes rewrites 127.0.0.1 to localhost inside request.url, which
 * would drop a host-only session cookie. Production origins are left as-is. */
export function redirectURL(request: Request, path: string): URL {
  const target = new URL(path, request.url);
  const host = (request.headers.get("host") ?? "").split(",")[0].trim();
  const hostName = host.replace(/:\d+$/, "");
  const loopback = (name: string) => name === "localhost" || name === "127.0.0.1";
  if (host && loopback(hostName) && loopback(target.hostname)) {
    target.host = host;
    target.protocol = "http:";
  }
  return target;
}
