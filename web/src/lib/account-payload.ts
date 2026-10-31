export type MeUser = { id: string; email: string };

/** `/api/auth/me` payload. `reauth` means a cookie was present and the API rejected it. */
export function accountFromMePayload(body: unknown): "reauth" | MeUser | null {
  if (!body || typeof body !== "object") return null;
  const record = body as { reauth?: unknown; user?: { id?: unknown; email?: unknown } | null };
  if (record.reauth === true) return "reauth";
  if (typeof record.user?.id === "string" && typeof record.user.email === "string") {
    return { id: record.user.id, email: record.user.email };
  }
  return null;
}
