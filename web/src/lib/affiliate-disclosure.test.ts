import assert from "node:assert/strict";
import test from "node:test";

import { isAffiliateUrl, tcgplayerMassEntryUrl } from "./affiliate";

const PREFIX = "https://tcgplayer.pxf.io/c/123456/789012/21018";

test("a plain TCGplayer link is not an affiliate link when no prefix is set", () => {
  const url = tcgplayerMassEntryUrl([{ name: "Lightning Bolt", quantity: 4 }]);
  assert.equal(url.startsWith("https://www.tcgplayer.com/massentry"), true);
  assert.equal(isAffiliateUrl(url, ""), false);
});

test("a wrapped TCGplayer link is an affiliate link only with the prefix", () => {
  const previous = process.env.NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL;
  process.env.NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL = PREFIX;
  try {
    const wrapped = `${PREFIX}?u=${encodeURIComponent("https://www.tcgplayer.com/massentry")}`;
    assert.equal(isAffiliateUrl(wrapped, PREFIX), true);
    assert.equal(isAffiliateUrl("https://www.tcgplayer.com/massentry", PREFIX), false);
    assert.equal(isAffiliateUrl("https://partner.tcgplayer.com/c/1/2/3?u=x", PREFIX), true);
  } finally {
    if (previous === undefined) delete process.env.NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL;
    else process.env.NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL = previous;
  }
});
