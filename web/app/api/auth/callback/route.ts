import { cookies } from "next/headers";
import { NEXT_COOKIE, SESSION_COOKIE, SESSION_DAYS, STATE_COOKIE, safeNext, sign } from "@/lib/session";

/** GitHub sends the visitor back here. Swap the code for their login and id, then forget GitHub's token. */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const store = await cookies();
  const expected = store.get(STATE_COOKIE)?.value;
  const next = safeNext(store.get(NEXT_COOKIE)?.value);
  store.delete(STATE_COOKIE);
  store.delete(NEXT_COOKIE);
  const back = (problem?: string) => Response.redirect(new URL(problem ? `${next}${next.includes("?") ? "&" : "?"}signin=${problem}` : next, url.origin).toString(), 302);

  const code = url.searchParams.get("code");
  if (!code || !expected || url.searchParams.get("state") !== expected) return back("failed");

  try {
    const exchange = await fetch("https://github.com/login/oauth/access_token", {
      method: "POST",
      headers: { accept: "application/json", "content-type": "application/json" },
      body: JSON.stringify({
        client_id: process.env.GITHUB_CLIENT_ID,
        client_secret: process.env.GITHUB_CLIENT_SECRET,
        code,
        redirect_uri: `${url.origin}/api/auth/callback`,
      }),
    });
    const { access_token: token } = (await exchange.json()) as { access_token?: string };
    if (!token) return back("failed");
    const me = await fetch("https://api.github.com/user", { headers: { authorization: `Bearer ${token}`, "user-agent": "github-wrapped" } });
    const user = (await me.json()) as { login?: string; id?: number };
    if (!user.login || typeof user.id !== "number") return back("failed");
    store.set(SESSION_COOKIE, sign({ login: user.login, id: user.id }, SESSION_DAYS * 86400), {
      httpOnly: true,
      secure: url.protocol === "https:",
      sameSite: "lax",
      path: "/",
      maxAge: SESSION_DAYS * 86400,
    });
    return back();
  } catch {
    return back("failed");
  }
}
