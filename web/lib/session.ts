// Signed tokens shared with the engine (roastmygithub/accounts.py makes and checks the same format):
// "v1.<base64url(json)>.<base64url(hmac-sha256)>" with json = {login, id, exp}. Server-only.
import { createHmac, timingSafeEqual } from "node:crypto";

export interface Account {
  login: string;
  id: number;
}

export const SESSION_COOKIE = "gw_session";
export const STATE_COOKIE = "gw_oauth_state";
export const NEXT_COOKIE = "gw_next";
export const SESSION_DAYS = 30;

function secret(): string {
  const value = process.env.SESSION_SECRET;
  if (!value) throw new Error("SESSION_SECRET is not set");
  return value;
}

const b64 = (data: Buffer | string) => Buffer.from(data).toString("base64url");

function mac(body: string): string {
  return b64(createHmac("sha256", secret()).update(`v1.${body}`).digest());
}

export function sign(account: Account, ttlSeconds: number): string {
  // Keys sorted, no spaces: the same bytes Python's json.dumps(sort_keys=True, separators=(",", ":")) writes.
  const payload = { exp: Math.floor(Date.now() / 1000) + ttlSeconds, id: account.id, login: account.login };
  const body = b64(JSON.stringify(payload));
  return `v1.${body}.${mac(body)}`;
}

export function verify(token: string | undefined): Account | null {
  if (!token) return null;
  const [version, body, signature] = token.split(".");
  if (version !== "v1" || !body || !signature) return null;
  const expected = Buffer.from(mac(body));
  const given = Buffer.from(signature);
  if (expected.length !== given.length || !timingSafeEqual(expected, given)) return null;
  try {
    const payload = JSON.parse(Buffer.from(body, "base64url").toString());
    if (typeof payload.exp !== "number" || payload.exp * 1000 < Date.now()) return null;
    if (typeof payload.login !== "string" || typeof payload.id !== "number") return null;
    return { login: payload.login, id: payload.id };
  } catch {
    return null;
  }
}

/** Only same-site paths: a sign-in link must never bounce people to another domain. */
export function safeNext(next: string | null | undefined): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}
