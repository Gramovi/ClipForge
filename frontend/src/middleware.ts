import { NextResponse, type NextRequest } from "next/server"

const PUBLIC = ["/login", "/register"]

/** Redirect anonymous visitors to /login (the API still enforces auth on every request). */
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl
  const hasSession = req.cookies.has("cf_session")
  if (!hasSession && !PUBLIC.includes(pathname)) {
    const url = req.nextUrl.clone()
    url.pathname = "/login"
    return NextResponse.redirect(url)
  }
  return NextResponse.next()
}

export const config = { matcher: ["/((?!api|_next|favicon.ico|.*\\..*).*)"] }
