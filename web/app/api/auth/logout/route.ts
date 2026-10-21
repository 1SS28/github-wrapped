import { cookies } from "next/headers";
import { SESSION_COOKIE, safeNext } from "@/lib/session";

export async function GET(request: Request) {
  const url = new URL(request.url);
  (await cookies()).delete(SESSION_COOKIE);
  return Response.redirect(new URL(safeNext(url.searchParams.get("next")), url.origin).toString(), 302);
}
