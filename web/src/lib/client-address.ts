const IP = /^(?:\d{1,3}\.){3}\d{1,3}$|^[0-9a-fA-F:]+$/;

function firstAddress(value: string | null | undefined): string | null {
  if (!value) return null;
  const first = value.split(",")[0]?.trim() ?? "";
  if (!first || first.length > 64 || !IP.test(first)) return null;
  return first;
}

/** TCP peer of this request, when the runtime exposes it. */
export function socketAddressOf(request: Request): string | null {
  const candidate = request as Request & { socket?: { remoteAddress?: unknown } };
  const remote = candidate.socket?.remoteAddress;
  return typeof remote === "string" ? remote : null;
}

const lastFallbackLog = new Map<string, number>();
const FALLBACK_LOG_MS = 60_000;

export function resetClientIpFallbackLog(): void {
  lastFallbackLog.clear();
}

function productionLogs(): boolean {
  return process.env.NODE_ENV === "production" || process.env.VERCEL_ENV === "production";
}

/** Warn when production has no platform client IP. At most once a minute per reason. */
export function noteClientIpFallback(
  reason: "vercel-unset" | "missing",
  now = Date.now(),
  log: (message: string) => void = (message) => console.warn(message),
  enabled = productionLogs(),
): void {
  if (!enabled) return;
  const previous = lastFallbackLog.get(reason) ?? 0;
  if (previous !== 0 && now - previous < FALLBACK_LOG_MS) return;
  lastFallbackLog.set(reason, now);
  log(
    reason === "vercel-unset"
      ? "client IP fell back to the socket address because VERCEL is unset"
      : "client IP is missing; rate limits may share one bucket",
  );
}

/**
 * Client IP to report to the API.
 *
 * On Vercel, `x-vercel-forwarded-for` is set by the edge and is not spoofable,
 * with `x-real-ip` as the fallback. Anywhere else those headers are ignored
 * and the socket address is used. The browser's `X-Forwarded-For` is never read.
 * A missing platform IP, or VERCEL being unset, is logged at most once a minute
 * in production.
 */
export function trustedClientAddress(
  headers: { get(name: string): string | null },
  socketAddress?: string | null,
  onVercel = Boolean(process.env.VERCEL),
): string | null {
  if (onVercel) {
    const platform = firstAddress(headers.get("x-vercel-forwarded-for")) ?? firstAddress(headers.get("x-real-ip"));
    if (platform) return platform;
    noteClientIpFallback("missing");
    return null;
  }
  const socket = firstAddress(socketAddress);
  noteClientIpFallback(socket ? "vercel-unset" : "missing");
  return socket;
}
