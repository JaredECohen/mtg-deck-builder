import { NextResponse, type NextFetchEvent, type NextRequest } from "next/server";

import { scheduleDocumentView } from "@/lib/usage";

export function middleware(request: NextRequest, event: NextFetchEvent) {
  scheduleDocumentView(
    {
      method: request.method,
      pathname: request.nextUrl.pathname,
      search: request.nextUrl.search,
      headers: request.headers,
    },
    (promise) => event.waitUntil(promise),
  );
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};
