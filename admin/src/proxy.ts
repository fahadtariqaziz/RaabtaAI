import { NextResponse, type NextRequest } from "next/server";

/** Optimistic guard only (Next 16 "proxy"): the real check is the API (401 → refresh → login).
 * `raabta_auth=1` is a non-sensitive hint cookie the client sets after a successful login/refresh;
 * the refresh token itself is httpOnly and scoped to /api/v1/auth, so it is invisible here. */
export function proxy(request: NextRequest) {
  if (!request.cookies.get("raabta_auth")) {
    const url = new URL("/login", request.url);
    const next = request.nextUrl.pathname;
    if (next !== "/") url.searchParams.set("next", next);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // everything except login/invite, API proxy, widget, Next internals and static files
  matcher: ["/((?!login|invite|api|widget|_next|favicon.ico|.*\\..*).*)"],
};
