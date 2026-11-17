import assert from "node:assert/strict";
import test from "node:test";

import { GET } from "../app/ads.txt/route";
import { adsTxt, publisherId } from "./ads";

const LINE = "google.com, pub-9525035178702963, DIRECT, f08c47fec0942fa0\n";

test("ads.txt is the publisher line for NEXT_PUBLIC_ADSENSE_CLIENT", () => {
  assert.equal(publisherId("ca-pub-9525035178702963"), "ca-pub-9525035178702963");
  assert.equal(adsTxt("ca-pub-9525035178702963"), LINE);
});

test("a missing or malformed publisher id yields no ads.txt", () => {
  assert.equal(adsTxt(undefined), null);
  assert.equal(adsTxt(null), null);
  assert.equal(adsTxt(""), null);
  assert.equal(adsTxt("pub-9525035178702963"), null);
  assert.equal(adsTxt("ca-pub-123"), null);
  assert.equal(adsTxt("ca-pub-9525035178702963 "), null);
  assert.equal(publisherId("not-a-publisher"), "");
});

test("the ads.txt route serves that line or no file", async () => {
  const previous = process.env.NEXT_PUBLIC_ADSENSE_CLIENT;
  process.env.NEXT_PUBLIC_ADSENSE_CLIENT = "ca-pub-9525035178702963";
  const served = GET();
  assert.equal(served.status, 200);
  assert.equal(await served.text(), LINE);

  process.env.NEXT_PUBLIC_ADSENSE_CLIENT = "";
  const missing = GET();
  assert.equal(missing.status, 404);

  process.env.NEXT_PUBLIC_ADSENSE_CLIENT = "ca-pub-nope";
  const malformed = GET();
  assert.equal(malformed.status, 404);
  process.env.NEXT_PUBLIC_ADSENSE_CLIENT = previous;
});
