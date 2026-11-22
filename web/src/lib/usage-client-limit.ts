// In-memory cap for POST /api/usage. The map holds an HMAC of the platform
// client address, not the address, and nothing is written to disk.

import { createHmac, randomBytes } from "node:crypto";

import { trustedClientAddress } from "./client-address";

const processKey = randomBytes(32);
const hits = new Map<string, number[]>();

export const usageClientBudget = { limit: 30, windowMs: 60_000 };

export function resetUsageClientLimit(): void {
  hits.clear();
}

/** Bucket id for this request. The address itself is not retained. */
export function usageClientBucket(
  headers: { get(name: string): string | null },
  socketAddress?: string | null,
): string {
  const address = trustedClientAddress(headers, socketAddress) ?? "unknown";
  return createHmac("sha256", processKey).update(address).digest("hex");
}

export function allowUsageClient(bucket: string, now = Date.now()): boolean {
  const cutoff = now - usageClientBudget.windowMs;
  const recent = (hits.get(bucket) ?? []).filter((stamp) => stamp > cutoff);
  if (recent.length >= usageClientBudget.limit) {
    hits.set(bucket, recent);
    return false;
  }
  recent.push(now);
  hits.set(bucket, recent);
  return true;
}

export function usageClientBuckets(): string[] {
  return [...hits.keys()];
}
