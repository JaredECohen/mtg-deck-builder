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

/**
 * Client IP to report to the API.
 *
 * On Vercel, `x-vercel-forwarded-for` is set by the edge and is not spoofable,
 * with `x-real-ip` as the fallback. Anywhere else those headers are ignored
 * and the socket address is used. The browser's `X-Forwarded-For` is never read.
 */
export function trustedClientAddress(
  headers: { get(name: string): string | null },
  socketAddress?: string | null,
  onVercel = Boolean(process.env.VERCEL),
): string | null {
  if (onVercel) {
    return firstAddress(headers.get("x-vercel-forwarded-for")) ?? firstAddress(headers.get("x-real-ip"));
  }
  return firstAddress(socketAddress);
}
