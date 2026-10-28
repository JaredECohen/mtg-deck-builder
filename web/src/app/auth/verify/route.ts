import { consumeVerifyPost, renderVerifyGet } from "@/lib/magic-link-verify";

export const dynamic = "force-dynamic";

/** Confirm page. Does not consume the magic-link token. */
export function GET(request: Request): Response {
  return renderVerifyGet(request);
}

/** Consumes the token only after the visitor presses Sign in. */
export function POST(request: Request): Promise<Response> {
  return consumeVerifyPost(request);
}
