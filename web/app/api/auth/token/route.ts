import { cookies } from "next/headers";
import { SESSION_COOKIE, sign, verify } from "@/lib/session";

/** Who is signed in, plus a one-hour token the browser sends to the engine. The session cookie never leaves this site. */
export async function GET() {
  const store = await cookies();
  const account = verify(store.get(SESSION_COOKIE)?.value);
  const headers = { "cache-control": "no-store" };
  if (!account) return Response.json({ login: null, token: null }, { headers });
  return Response.json({ login: account.login, token: sign(account, 3600) }, { headers });
}
