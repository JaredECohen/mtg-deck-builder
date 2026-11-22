import { after } from "next/server";

import { clientUsagePayload, postUsageEvent } from "@/lib/usage";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  let payload: Awaited<ReturnType<typeof clientUsagePayload>> = null;
  try {
    payload = await clientUsagePayload(request);
  } catch {
    payload = null;
  }
  if (payload) {
    const event = payload;
    const work = () => postUsageEvent(event).catch(() => undefined);
    try {
      after(() => {
        void work();
      });
    } catch {
      void work();
    }
  }
  return new Response(null, { status: 204 });
}
