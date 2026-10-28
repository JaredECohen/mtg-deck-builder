/** Where to send a browser when the API rejected a presented session. */
export function signInPathForStatus(status: number, detail: unknown): "/signin?error=expired" | null {
  if (status === 401 && detail === "Sign in required.") return "/signin?error=expired";
  return null;
}
