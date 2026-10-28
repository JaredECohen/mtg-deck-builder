export const SESSION_COOKIE = "decklab_session";
export const PREAUTH_COOKIE = "decklab_preauth";
const THIRTY_DAYS = 60 * 60 * 24 * 30;
export const PREAUTH_MAX_AGE = 20 * 60;

export function cookieSecure(): boolean {
  return process.env.NODE_ENV === "production";
}

export function sessionCookie(maxAge = THIRTY_DAYS) {
  return {
    httpOnly: true,
    secure: cookieSecure(),
    sameSite: "lax" as const,
    path: "/",
    maxAge
  };
}

/** Short-lived cookie set when a magic link is requested. Sent only to the confirm page. */
export function preauthCookie(maxAge = PREAUTH_MAX_AGE) {
  return {
    httpOnly: true,
    secure: cookieSecure(),
    sameSite: "lax" as const,
    path: "/auth/verify",
    maxAge
  };
}

const OPAQUE_TOKEN = /^[A-Za-z0-9_-]{20,200}$/;

export function isOpaqueToken(value: string | null | undefined): value is string {
  return typeof value === "string" && OPAQUE_TOKEN.test(value);
}

export function readCookie(request: Request, name: string): string | null {
  const header = request.headers.get("cookie");
  if (!header) return null;
  for (const part of header.split(";")) {
    const trimmed = part.trim();
    const eq = trimmed.indexOf("=");
    if (eq === -1 || trimmed.slice(0, eq) !== name) continue;
    let value = trimmed.slice(eq + 1);
    try {
      value = decodeURIComponent(value);
    } catch {
      return null;
    }
    return value;
  }
  return null;
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
  if (process.env.NODE_ENV === "production") return false;
  if ((process.env.ENV ?? "").toLowerCase() === "production") return false;
  if ((process.env.FLY_APP_NAME ?? "").trim()) return false;
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
