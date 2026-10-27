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
 * Every anonymous deck is owned by the site's own API key, so without a session
 * the API cannot tell one visitor from another. Listing or editing a library
 * therefore needs a signed-in session. An anonymous browser can still read or
 * delete a deck by the id it was given when it saved it.
 */
export function requiresSession(method: string, decoded: string): boolean {
  const verb = method.toUpperCase();
  if (verb === "GET" || verb === "HEAD") {
    return decoded === "/v1/decks/history" || decoded.startsWith("/v1/decks/history/");
  }
  if (verb === "PATCH") return decoded.startsWith("/v1/decks/saved/");
  return false;
}
