// In-memory cap for POST /api/usage. The map holds an HMAC of the platform
// client address, not the address, and nothing is written to disk.

import { createHmac, randomBytes } from "node:crypto";

import { trustedClientAddress } from "./client-address";

const processKey = randomBytes(32);
const hits = new Map<string, number[]>();

export const usageClientBudget = { limit: 30, windowMs: 60_000, maxBuckets: 4096 };

function sweepIdle(now: number): void {
  const cutoff = now - usageClientBudget.windowMs;
  for (const [key, stamps] of hits) {
    const recent = stamps.filter((stamp) => stamp > cutoff);
    if (recent.length === 0) hits.delete(key);
    else hits.set(key, recent);
  }
}

/** Drop the oldest buckets until a new key fits. Map order is insertion order. */
function evictUntilRoom(bucket: string): void {
  if (hits.has(bucket)) return;
  while (hits.size >= usageClientBudget.maxBuckets) {
    const oldest = hits.keys().next().value;
    if (oldest === undefined) return;
    hits.delete(oldest);
  }
}

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
  sweepIdle(now);
  evictUntilRoom(bucket);
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
