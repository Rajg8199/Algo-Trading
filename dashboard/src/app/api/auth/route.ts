import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE, authDisabled, sessionToken } from "@/lib/auth";

export async function POST(request: NextRequest) {
  if (authDisabled()) {
    return NextResponse.json({ ok: true, note: "auth disabled (no DASHBOARD_PASSWORD)" });
  }
  const { password } = (await request.json()) as { password?: string };
  if (!password || password !== process.env.DASHBOARD_PASSWORD) {
    return NextResponse.json({ ok: false }, { status: 401 });
  }
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, await sessionToken(password), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    maxAge: 60 * 60 * 24 * 7,
    path: "/",
  });
  return response;
}
