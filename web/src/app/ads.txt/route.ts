import { adsTxt } from "@/lib/ads";

// Served at /ads.txt. 404 until AdSense is configured, so the site never
// publishes an empty or placeholder seller declaration.
export function GET() {
  const body = adsTxt();
  if (!body) return new Response("Not found\n", { status: 404 });
  return new Response(body, {
    headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "public, max-age=3600" },
  });
}
