// Which /api/backend requests the proxy refuses before they reach the API.
//
// Checks run on the decoded path, because the API decodes it before routing:
// "/v1/%61uth/verify" must count as "/v1/auth/verify".

/** The path the API will route, or null when it is not valid percent-encoding. */
export function decodedApiPath(path: string): string | null {
  try {
    return decodeURIComponent(path);
  } catch {
    return null;
  }
}

/** Sign-in routes are served by /api/auth/*, which keeps tokens in an httpOnly cookie. */
export function isAuthPath(decoded: string): boolean {
  return decoded === "/v1/auth" || decoded.startsWith("/v1/auth/");
}

/**
 * Listing a library, renaming a deck, or publishing it needs a signed-in
 * session. The cookie check here is only a shape check: a made-up value still
 * matches. The API rejects that value with 401 instead of falling back to the
 * shared API-key owner.
 *
 * Anonymous delete is still forwarded. The API requires the per-deck edit
 * secret returned once when that deck was saved; the id alone is not enough.
 */
export function requiresSession(method: string, decoded: string): boolean {
  const verb = method.toUpperCase();
  if (verb === "GET" || verb === "HEAD") {
    return decoded === "/v1/decks/history" || decoded.startsWith("/v1/decks/history/");
  }
  if (verb === "PATCH") return decoded.startsWith("/v1/decks/saved/");
  return false;
}
