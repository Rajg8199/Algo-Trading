import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE, authDisabled, sessionToken } from "@/lib/auth";

export async function middleware(request: NextRequest) {
  if (authDisabled()) return NextResponse.next();

  const cookie = request.cookies.get(SESSION_COOKIE)?.value;
  const expected = await sessionToken(process.env.DASHBOARD_PASSWORD as string);
  if (cookie === expected) return NextResponse.next();

  const login = new URL("/login", request.url);
  login.searchParams.set("next", request.nextUrl.pathname);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!login|api/auth|_next/static|_next/image|favicon.ico).*)"],
};
