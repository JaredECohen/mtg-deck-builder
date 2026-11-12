import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { mdxComponentsForPost } from "../components/blog/mdx-components";
import { CardDetailModal } from "../components/workshop/card-detail-modal";
import { ShopDeckPanel } from "../components/workshop/deck-results";
import { PreconResult } from "../components/workshop/precon-upgrade";
import type { CardDetailState } from "../hooks/use-card-detail";
import {
  AFFILIATE_DISCLOSURE,
  TCG_SUB_ID,
  blogSubId,
  canonicalTcgplayerUrl,
  externalAnchorRel,
  isAffiliateUrl,
  sanitizeSubId,
  subIdFromPath,
  tcgplayerAffiliate,
  tcgplayerBuyUrl,
  tcgplayerMassEntryUrl,
} from "./affiliate";
import type { CardRecord, DeckResponse, PreconUpgradeResponse } from "./types";

const PREFIX = "https://partner.tcgplayer.com/c/123456/789012/21018";
const PROPERTY_ID = "1111111";
const PRODUCT = "https://www.tcgplayer.com/product/42/magic-lightning-bolt";

const ENV_KEYS = ["NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL", "NEXT_PUBLIC_TCGPLAYER_PARTNER_PROPERTY_ID"] as const;

function withAffiliateEnv(values: Partial<Record<(typeof ENV_KEYS)[number], string>>, run: () => void) {
  const previous = new Map(ENV_KEYS.map((key) => [key, process.env[key]]));
  try {
    for (const key of ENV_KEYS) {
      const value = values[key];
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    run();
  } finally {
    for (const [key, value] of previous) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

function queryKeys(url: string): string[] {
  return new URL(url).search.slice(1).split("&").map((part) => part.split("=")[0] ?? "");
}

test("a plain TCGplayer link is not an affiliate link when no prefix is set", () => {
  withAffiliateEnv({}, () => {
    const url = tcgplayerMassEntryUrl([{ name: "Lightning Bolt", quantity: 4 }]);
    assert.equal(url.startsWith("https://www.tcgplayer.com/massentry"), true);
    assert.equal(isAffiliateUrl(url, ""), false);
    assert.equal(url.includes("subId1"), false);
    assert.equal(url.includes("partnerpropertyid"), false);
  });
});

test("a wrapped TCGplayer link is an affiliate link only with the prefix", () => {
  withAffiliateEnv({ NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL: PREFIX }, () => {
    const wrapped = `${PREFIX}?u=${encodeURIComponent("https://www.tcgplayer.com/massentry")}`;
    assert.equal(isAffiliateUrl(wrapped, PREFIX), true);
    assert.equal(isAffiliateUrl("https://www.tcgplayer.com/massentry", PREFIX), false);
    assert.equal(isAffiliateUrl("https://partner.tcgplayer.com/c/1/2/3?u=x", PREFIX), true);
    assert.equal(isAffiliateUrl("https://evilpxf.io.example.com/?u=x", PREFIX), false);
    assert.equal(externalAnchorRel("https://tcgplayer.pxf.io/c/1/2/3?u=deck"), "sponsored nofollow noopener noreferrer");
    assert.equal(externalAnchorRel("https://partner.tcgplayer.com/c/1/2/3"), "sponsored nofollow noopener noreferrer");
    assert.equal(externalAnchorRel("https://magic.wizards.com/en/news"), "noopener noreferrer");
    assert.equal(externalAnchorRel("https://www.tcgplayer.com/product/42"), "noopener noreferrer");
  });
});

test("wrap includes subId1, u, and partnerpropertyid in Impact's order", () => {
  withAffiliateEnv(
    {
      NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL: `${PREFIX}?leftover=1`,
      NEXT_PUBLIC_TCGPLAYER_PARTNER_PROPERTY_ID: PROPERTY_ID,
    },
    () => {
      const url = tcgplayerAffiliate(PRODUCT, { subId: "home" });
      assert.equal(
        url,
        `${PREFIX}?subId1=home&u=${encodeURIComponent(PRODUCT)}&partnerpropertyid=${PROPERTY_ID}`,
      );
      assert.equal(url.split("?").length, 2);
      assert.deepEqual(queryKeys(url), ["subId1", "u", "partnerpropertyid"]);
      assert.equal(new URL(url).searchParams.get("u"), PRODUCT);
    },
  );
});

test("wrap omits empty subId1 and partnerpropertyid", () => {
  withAffiliateEnv({ NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL: PREFIX }, () => {
    const url = tcgplayerAffiliate(PRODUCT, { subId: "" });
    assert.equal(url, `${PREFIX}?u=${encodeURIComponent(PRODUCT)}`);
    assert.equal(url.includes("subId1"), false);
    assert.equal(url.includes("partnerpropertyid"), false);
  });
});

test("subId1 is sanitized and capped", () => {
  withAffiliateEnv({ NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL: PREFIX }, () => {
    const url = tcgplayerAffiliate(PRODUCT, { subId: "blog/mill deck guide!!" });
    assert.equal(new URL(url).searchParams.get("subId1"), "blog-mill-deck-guide");
    const long = sanitizeSubId(`blog-${"a".repeat(80)}`);
    assert.ok(long.length <= 64);
    assert.equal(blogSubId("mill-deck-guide"), "blog-mill-deck-guide");
    assert.equal(subIdFromPath("/"), "home");
    assert.equal(subIdFromPath("/blog/mill-deck-guide"), "blog-mill-deck-guide");
    assert.equal(subIdFromPath("/method"), "method");
  });
});

test("unwraps pxf.io and partner.tcgplayer.com, including nested wrappers, then re-wraps", () => {
  withAffiliateEnv(
    {
      NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL: PREFIX,
      NEXT_PUBLIC_TCGPLAYER_PARTNER_PROPERTY_ID: PROPERTY_ID,
    },
    () => {
      const pxf = `https://tcgplayer.pxf.io/c/1/2/3?u=${encodeURIComponent(PRODUCT)}`;
      const partner = `https://partner.tcgplayer.com/c/4931599/1830156/21018?subId1=api&u=${encodeURIComponent(PRODUCT)}`;
      const nested = `https://partner.tcgplayer.com/c/9/9/9?u=${encodeURIComponent(pxf)}`;
      for (const raw of [pxf, partner, nested]) {
        const url = tcgplayerAffiliate(raw, { subId: TCG_SUB_ID.workshop });
        assert.equal(new URL(url).searchParams.get("u"), PRODUCT);
        assert.equal(new URL(url).searchParams.get("subId1"), "workshop");
        assert.equal(url.includes("4931599"), false);
        assert.equal(url.includes("/c/1/2/3"), false);
        assert.equal(url.includes("/c/9/9/9"), false);
        assert.equal(canonicalTcgplayerUrl(raw), PRODUCT);
      }
      const once = tcgplayerAffiliate(PRODUCT, { subId: "home" });
      assert.equal(tcgplayerAffiliate(once, { subId: "home" }), once);
      assert.equal(new URL(tcgplayerAffiliate(once, { subId: "workshop" })).searchParams.get("u"), PRODUCT);
    },
  );
});

test("an unset prefix unwraps to the canonical tcgplayer.com URL", () => {
  withAffiliateEnv({}, () => {
    const wrapped = `https://partner.tcgplayer.com/c/4931599/1830156/21018?subId1=api&u=${encodeURIComponent(PRODUCT)}`;
    assert.equal(tcgplayerAffiliate(wrapped), PRODUCT);
    assert.equal(tcgplayerAffiliate(PRODUCT), PRODUCT);
    assert.equal(tcgplayerBuyUrl(wrapped, "Lightning Bolt"), PRODUCT);
  });
});

test("non-tcgplayer destinations are refused", () => {
  withAffiliateEnv({ NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL: PREFIX }, () => {
    assert.equal(tcgplayerAffiliate("https://evil.example.com/phish"), "");
    const hostile = `https://tcgplayer.pxf.io/c/1/2/3?u=${encodeURIComponent("https://evil.example.com/phish")}`;
    assert.equal(tcgplayerAffiliate(hostile), "");
    assert.equal(tcgplayerAffiliate("https://evilpxf.io.example.com/?u=" + encodeURIComponent(PRODUCT)), "");
    const fallback = tcgplayerBuyUrl(hostile, "Lightning Bolt", { subId: "workshop" });
    assert.equal(fallback.startsWith(`${PREFIX}?subId1=workshop&u=`), true);
    assert.equal(new URL(fallback).searchParams.get("u")?.includes("tcgplayer.com/search"), true);
    assert.equal(fallback.includes("evil.example.com"), false);
  });
});

test("affiliate: false stays on the canonical URL even when the prefix is set", () => {
  withAffiliateEnv(
    {
      NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL: PREFIX,
      NEXT_PUBLIC_TCGPLAYER_PARTNER_PROPERTY_ID: PROPERTY_ID,
    },
    () => {
      const wrapped = `https://partner.tcgplayer.com/c/9/9/9?u=${encodeURIComponent(PRODUCT)}`;
      assert.equal(tcgplayerAffiliate(wrapped, { affiliate: false, subId: "blog-mill-deck-guide" }), PRODUCT);
      const mass = tcgplayerMassEntryUrl([{ name: "Lightning Bolt", quantity: 4 }], { affiliate: false, subId: "blog-x" });
      assert.equal(mass.startsWith("https://www.tcgplayer.com/massentry"), true);
      assert.equal(isAffiliateUrl(mass), false);
    },
  );
});

function boltCard(tcgplayer: string): CardRecord {
  return {
    name: "Lightning Bolt",
    mana_cost: "{R}",
    mana_value: 1,
    colors: ["R"],
    color_identity: ["R"],
    type_line: "Instant",
    oracle_text: "Deal 3 damage.",
    keywords: [],
    image_uris: {},
    faces: [],
    legalities: {},
    tags: [],
    purchase_links: { tcgplayer },
  };
}

function cardDetail(card: CardRecord | null): CardDetailState {
  return {
    isOpen: true,
    name: "Lightning Bolt",
    card,
    loading: false,
    error: null,
    context: {},
    similar: [],
    similarLoading: false,
    similarError: null,
    open: async () => {},
    close: () => {},
  };
}

test("the card modal discloses affiliate links only when they are wrapped", () => {
  const foreign = `https://partner.tcgplayer.com/c/4931599/1830156/21018?subId1=api&u=${encodeURIComponent(PRODUCT)}`;
  withAffiliateEnv({}, () => {
    const html = renderToStaticMarkup(
      createElement(CardDetailModal, { detail: cardDetail(boltCard(foreign)), subId: TCG_SUB_ID.workshop }),
    );
    assert.equal(html.includes(AFFILIATE_DISCLOSURE), false);
    assert.equal(html.includes(`href="${PRODUCT}"`), true);
    assert.equal(html.includes("sponsored"), false);
    assert.equal(html.includes("4931599"), false);
  });
  withAffiliateEnv(
    {
      NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL: PREFIX,
      NEXT_PUBLIC_TCGPLAYER_PARTNER_PROPERTY_ID: PROPERTY_ID,
    },
    () => {
      const html = renderToStaticMarkup(
        createElement(CardDetailModal, { detail: cardDetail(boltCard(foreign)), subId: TCG_SUB_ID.workshop }),
      );
      assert.equal(html.includes(AFFILIATE_DISCLOSURE), true);
      assert.equal(html.includes("subId1=workshop"), true);
      assert.equal(html.includes(`partnerpropertyid=${PROPERTY_ID}`), true);
      assert.equal(html.includes("4931599"), false);
      assert.equal(html.includes('rel="sponsored nofollow noopener noreferrer"'), true);
    },
  );
});

test("shop this deck discloses affiliate links only when they are wrapped", () => {
  const deck = {
    format: "modern",
    commander: null,
    mainboard: [{ name: "Lightning Bolt", quantity: 4 }],
    sideboard: [],
  } as unknown as DeckResponse;
  withAffiliateEnv({}, () => {
    const html = renderToStaticMarkup(createElement(ShopDeckPanel, { deck, subId: TCG_SUB_ID.home }));
    assert.equal(html.includes(AFFILIATE_DISCLOSURE), false);
    assert.equal(html.includes("https://www.tcgplayer.com/massentry"), true);
    assert.equal(html.includes("sponsored"), false);
  });
  withAffiliateEnv(
    {
      NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL: PREFIX,
      NEXT_PUBLIC_TCGPLAYER_PARTNER_PROPERTY_ID: PROPERTY_ID,
    },
    () => {
      const html = renderToStaticMarkup(createElement(ShopDeckPanel, { deck, subId: TCG_SUB_ID.home }));
      assert.equal(html.includes(AFFILIATE_DISCLOSURE), true);
      assert.equal(html.includes("subId1=home"), true);
      assert.equal(html.includes(`partnerpropertyid=${PROPERTY_ID}`), true);
      assert.equal(html.includes('rel="sponsored nofollow noopener noreferrer"'), true);
    },
  );
});

test("the precon cart re-wraps the API link and discloses only when wrapped", () => {
  const apiCart = `${PREFIX}?subId1=api&u=${encodeURIComponent("https://www.tcgplayer.com/massentry?productline=Magic&c=1%20Sol%20Ring")}`;
  const result = {
    precon_id: "demo",
    name: "Goblin Test",
    commander: "Krenko, Mob Boss",
    commanders: ["Krenko, Mob Boss"],
    budget_usd: 15,
    total_cost_usd: 1,
    swaps: [],
    legality: {
      is_legal: true,
      errors: [],
      warnings: [],
      score: { legality: 1, mana: 1, synergy: 1, competitiveness: 1, role_balance: 1, curve: 1, total: 1 },
    },
    bracket: {
      estimated: 2,
      target: 2,
      game_changers: [],
      mass_land_denial: [],
      extra_turns: [],
      tutors: [],
      two_card_combos: [],
      notes: [],
    },
    tcgplayer_cart_url: apiCart,
    warnings: [],
    upgraded_mainboard: [],
  } as unknown as PreconUpgradeResponse;
  withAffiliateEnv({}, () => {
    const html = renderToStaticMarkup(createElement(PreconResult, { result, onOpenCard: () => {} }));
    assert.equal(html.includes(AFFILIATE_DISCLOSURE), false);
    assert.equal(html.includes("https://www.tcgplayer.com/massentry"), true);
    assert.equal(html.includes("subId1=api"), false);
    assert.equal(html.includes("sponsored"), false);
  });
  withAffiliateEnv(
    {
      NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL: PREFIX,
      NEXT_PUBLIC_TCGPLAYER_PARTNER_PROPERTY_ID: PROPERTY_ID,
    },
    () => {
      const html = renderToStaticMarkup(createElement(PreconResult, { result, onOpenCard: () => {} }));
      assert.equal(html.includes(AFFILIATE_DISCLOSURE), true);
      assert.equal(html.includes("subId1=workshop-precon"), true);
      assert.equal(html.includes("subId1=api"), false);
      assert.equal(html.includes(`partnerpropertyid=${PROPERTY_ID}`), true);
    },
  );
  const empty = { ...result, tcgplayer_cart_url: null };
  withAffiliateEnv(
    { NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL: PREFIX, NEXT_PUBLIC_TCGPLAYER_PARTNER_PROPERTY_ID: PROPERTY_ID },
    () => {
      const html = renderToStaticMarkup(createElement(PreconResult, { result: empty, onOpenCard: () => {} }));
      assert.equal(html.includes(AFFILIATE_DISCLOSURE), false);
      assert.equal(html.includes("Buy the adds"), false);
    },
  );
});

test("reviewed guides wrap buy links and unreviewed guides do not", () => {
  withAffiliateEnv(
    {
      NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL: PREFIX,
      NEXT_PUBLIC_TCGPLAYER_PARTNER_PROPERTY_ID: PROPERTY_ID,
    },
    () => {
      const reviewed = renderToStaticMarkup(
        createElement(mdxComponentsForPost(true, "mill-deck-guide").DeckBlock, { id: "mono-red-burn" }),
      );
      assert.equal(reviewed.includes("subId1=blog-mill-deck-guide"), true);
      assert.equal(reviewed.includes(`partnerpropertyid=${PROPERTY_ID}`), true);
      assert.equal(reviewed.includes(AFFILIATE_DISCLOSURE), true);
      assert.equal(reviewed.includes('rel="sponsored nofollow noopener noreferrer"'), true);

      const unreviewed = renderToStaticMarkup(
        createElement(mdxComponentsForPost(false, "mill-deck-guide").DeckBlock, { id: "mono-red-burn" }),
      );
      assert.equal(unreviewed.includes("https://www.tcgplayer.com/massentry"), true);
      assert.equal(unreviewed.includes("partner.tcgplayer.com"), false);
      assert.equal(unreviewed.includes(AFFILIATE_DISCLOSURE), false);
      assert.equal(unreviewed.includes("sponsored"), false);
      assert.equal(unreviewed.includes('rel="noopener noreferrer"'), true);
    },
  );
});
