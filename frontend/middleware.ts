/**
 * Sets durable `aid` (anon_id, 1 year) and rolling `sid` (session_id, 30 days)
 * cookies. The backend reads these to stitch journey events to leads/users.
 */
import { NextRequest, NextResponse } from "next/server";

const ONE_YEAR  = 60 * 60 * 24 * 365;
const ONE_MONTH = 60 * 60 * 24 * 30;

function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return ([1e7] as unknown as string + -1e3 + -4e3 + -8e3 + -1e11)
    .replace(/[018]/g, (c) =>
      (Number(c) ^ (Math.random() * 16) >> (Number(c) / 4)).toString(16),
    );
}

export function middleware(req: NextRequest) {
  const res = NextResponse.next();
  let aid = req.cookies.get("aid")?.value;
  if (!aid) {
    aid = uuid();
    res.cookies.set("aid", aid,
      { httpOnly: true, secure: true, sameSite: "lax", maxAge: ONE_YEAR });
  }
  let sid = req.cookies.get("sid")?.value;
  if (!sid) {
    sid = uuid();
    res.cookies.set("sid", sid,
      { httpOnly: true, secure: true, sameSite: "lax", maxAge: ONE_MONTH });
  }
  return res;
}

export const config = {
  matcher: "/((?!_next/static|_next/image|favicon.ico|.*\\..*).*)",
};
