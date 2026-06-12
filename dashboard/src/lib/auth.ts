/** Minimal session auth: a SHA-256 of DASHBOARD_PASSWORD in an httpOnly
 * cookie. If DASHBOARD_PASSWORD is unset, auth is disabled (local dev).
 * Production network exposure is additionally guarded by Caddy basic-auth;
 * this layer exists so the app is never the only thing standing. */

export const SESSION_COOKIE = "tp_session";

export async function sessionToken(password: string): Promise<string> {
  const bytes = new TextEncoder().encode(`tp-dashboard:${password}`);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function authDisabled(): boolean {
  return !process.env.DASHBOARD_PASSWORD;
}
