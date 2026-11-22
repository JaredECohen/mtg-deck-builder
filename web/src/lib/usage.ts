// Coarse location for first-party usage events.
//
// Country, region, and city come from Vercel's platform headers, read on the
// server. The browser never supplies them. Latitude, longitude, postal code,
// and forwarded-for are not read. Failures are swallowed by the caller.

import { ANALYTICS_EVENT_PROPS, redactUsagePath } from "./analytics";
import { apiBase } from "./session-cookie";

export const USAGE_INGEST_HEADER = "x-usage-ingest-secret";
const COUNTRY_HEADER = "x-vercel-ip-country";
const REGION_HEADER = "x-vercel-ip-country-region";
const CITY_HEADER = "x-vercel-ip-city";

function isFunnelEvent(name: string): boolean {
  return Object.prototype.hasOwnProperty.call(ANALYTICS_EVENT_PROPS, name);
}

const STATIC_EXT = /\.(?:avif|css|gif|ico|jpeg|jpg|js|map|png|svg|txt|webmanifest|webp|xml)$/i;
const USAGE_TIMEOUT_MS = 1500;

export type HeaderSource = { get(name: string): string | null };

export type CoarseLocation = {
  country: string | null;
  region: string | null;
  city: string | null;
};

export type UsagePayload = CoarseLocation & {
  event: string;
  path: string;
};

export function decodeGeoHeader(value: string | null): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  try {
    return decodeURIComponent(trimmed);
  } catch {
    return trimmed;
  }
}

function looksLikeIp(value: string): boolean {
  if (/^(?:\d{1,3}\.){3}\d{1,3}$/.test(value)) return true;
  return value.includes(":") && /^[0-9a-fA-F:]+$/.test(value);
}

function geoField(value: string | null): string | null {
  const decoded = decodeGeoHeader(value);
  if (!decoded || looksLikeIp(decoded)) return null;
  return decoded;
}

/** Platform coarse location. Missing headers are null, not an error. */
export function readCoarseLocation(headers: HeaderSource): CoarseLocation {
  return {
    country: geoField(headers.get(COUNTRY_HEADER)),
    region: geoField(headers.get(REGION_HEADER)),
    city: geoField(headers.get(CITY_HEADER)),
  };
}

export function isSkippedUsagePath(pathname: string): boolean {
  if (pathname.startsWith("/_next")) return true;
  if (pathname === "/api" || pathname.startsWith("/api/")) return true;
  if (pathname === "/health" || pathname.startsWith("/health/")) return true;
  if (pathname === "/v1/usage" || pathname.startsWith("/v1/usage/")) return true;
  return STATIC_EXT.test(pathname);
}

/** Document loads and App Router navigations. Prefetch, assets, and /api are skipped. */
export function shouldRecordDocumentView(method: string, pathname: string, headers: HeaderSource): boolean {
  if (method !== "GET") return false;
  if (isSkippedUsagePath(pathname)) return false;
  if (headers.get("next-router-prefetch") === "1") return false;
  const purpose = (headers.get("purpose") ?? headers.get("sec-purpose") ?? "").toLowerCase();
  if (purpose === "prefetch") return false;
  if (headers.get("rsc") === "1") return true;
  const accept = (headers.get("accept") ?? "").toLowerCase();
  return accept.length === 0 || accept.includes("text/html") || accept.includes("*/*");
}

export function documentViewPayload(pathname: string, search: string, headers: HeaderSource): UsagePayload | null {
  const path = redactUsagePath(`${pathname}${search}`);
  if (!path) return null;
  return { event: "page_view", path, ...readCoarseLocation(headers) };
}

/**
 * Funnel event from the browser route. Geo is taken from `headers` only.
 * Fields on the JSON body other than event and path are ignored.
 */
export async function clientUsagePayload(request: Request): Promise<UsagePayload | null> {
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declared) && declared > 2048) return null;
  let raw = "";
  try {
    raw = await request.text();
  } catch {
    return null;
  }
  if (raw.length > 2048) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const body = parsed as Record<string, unknown>;
  if (typeof body.event !== "string" || !isFunnelEvent(body.event)) return null;
  if (typeof body.path !== "string") return null;
  const path = redactUsagePath(body.path);
  if (!path) return null;
  return { event: body.event, path, ...readCoarseLocation(request.headers) };
}

/** POST the event to Fly. No-ops when the secret is unset. Never throws. */
export async function postUsageEvent(payload: UsagePayload, fetchImpl: typeof fetch = fetch): Promise<void> {
  const secret = process.env.USAGE_INGEST_SECRET?.trim();
  if (!secret) return;
  try {
    await fetchImpl(`${apiBase()}/v1/usage`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        [USAGE_INGEST_HEADER]: secret,
      },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(USAGE_TIMEOUT_MS),
    });
  } catch {
    // A usage outage must not break the page.
  }
}

/** Schedule a page view without awaiting it. `waitUntil` is Next's event.waitUntil. */
export function scheduleDocumentView(
  input: { method: string; pathname: string; search: string; headers: HeaderSource },
  waitUntil: (promise: Promise<unknown>) => void,
  post: (payload: UsagePayload) => Promise<void> = postUsageEvent,
): void {
  if (!shouldRecordDocumentView(input.method, input.pathname, input.headers)) return;
  const payload = documentViewPayload(input.pathname, input.search, input.headers);
  if (!payload) return;
  waitUntil(post(payload).catch(() => undefined));
}
