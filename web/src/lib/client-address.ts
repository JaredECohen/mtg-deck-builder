const IP = /^(?:\d{1,3}\.){3}\d{1,3}$|^[0-9a-fA-F:]+$/;

function firstAddress(value: string | null): string | null {
  if (!value) return null;
  const first = value.split(",")[0]?.trim() ?? "";
  if (!first || first.length > 64 || !IP.test(first)) return null;
  return first;
}

/**
 * Client IP to report to the API.
 *
 * `x-vercel-forwarded-for` is set by Vercel's edge and is not spoofable by the
 * browser. `x-real-ip` is the fallback on other platforms. The browser's
 * `X-Forwarded-For` is never read.
 */
export function trustedClientAddress(headers: { get(name: string): string | null }): string | null {
  return firstAddress(headers.get("x-vercel-forwarded-for")) ?? firstAddress(headers.get("x-real-ip"));
}
