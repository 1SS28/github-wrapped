import { randomBytes } from "node:crypto";
import { cookies } from "next/headers";
import { NEXT_COOKIE, STATE_COOKIE, safeNext } from "@/lib/session";

/** Start "Sign in with GitHub": remember where to come back to, then send the visitor to GitHub. */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const state = randomBytes(24).toString("base64url");
  const store = await cookies();
  const opts = { httpOnly: true, secure: url.protocol === "https:", sameSite: "lax" as const, path: "/", maxAge: 600 };
  store.set(STATE_COOKIE, state, opts);
  store.set(NEXT_COOKIE, safeNext(url.searchParams.get("next")), opts);
  const github = new URL("https://github.com/login/oauth/authorize");
  github.searchParams.set("client_id", process.env.GITHUB_CLIENT_ID ?? "");
  github.searchParams.set("redirect_uri", `${url.origin}/api/auth/callback`);
  github.searchParams.set("state", state);
  github.searchParams.set("allow_signup", "true");
  // No scope: GitHub then grants read access to public profile information only.
  return Response.redirect(github.toString(), 302);
}
