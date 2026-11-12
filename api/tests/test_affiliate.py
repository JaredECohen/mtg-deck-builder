"""TCGplayer affiliate link construction."""

from urllib.parse import parse_qsl, quote, urlparse

import pytest

from app.services import affiliate

PREFIX = "https://partner.tcgplayer.com/c/123456/789012/21018"
PROPERTY_ID = "1111111"
PRODUCT = "https://www.tcgplayer.com/product/42/magic-lightning-bolt"


def _keys(url: str) -> list[str]:
    return [key for key, _ in parse_qsl(urlparse(url).query, keep_blank_values=True)]


def _u(url: str) -> str:
    return dict(parse_qsl(urlparse(url).query))["u"]


def test_affiliate_unset_returns_destination(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", "")
    monkeypatch.setattr(affiliate, "TCGPLAYER_PARTNER_PROPERTY_ID", PROPERTY_ID)
    assert affiliate.tcgplayer_affiliate(PRODUCT) == PRODUCT


def test_affiliate_wraps_destination(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", PREFIX)
    monkeypatch.setattr(affiliate, "TCGPLAYER_PARTNER_PROPERTY_ID", "")
    url = affiliate.tcgplayer_affiliate(PRODUCT)
    assert url.startswith(f"{PREFIX}?subId1=api&u=")
    # Destination is URL-encoded inside the u= param, not left in the prefix.
    assert "www.tcgplayer.com" not in url.split("&u=", 1)[0]
    assert "tcgplayer.com%2Fproduct" in url
    assert _keys(url) == ["subId1", "u"]
    assert _u(url) == PRODUCT


def test_affiliate_wraps_all_params_in_impact_order(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", PREFIX)
    monkeypatch.setattr(affiliate, "TCGPLAYER_PARTNER_PROPERTY_ID", PROPERTY_ID)
    url = affiliate.tcgplayer_affiliate(PRODUCT, sub_id="home")
    encoded = quote(PRODUCT, safe="")
    assert url == f"{PREFIX}?subId1=home&u={encoded}&partnerpropertyid={PROPERTY_ID}"
    assert url.count("?") == 1
    assert _keys(url) == ["subId1", "u", "partnerpropertyid"]


def test_affiliate_omits_empty_optional_params(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", f"{PREFIX}?leftover=1")
    monkeypatch.setattr(affiliate, "TCGPLAYER_PARTNER_PROPERTY_ID", "")
    url = affiliate.tcgplayer_affiliate(PRODUCT, sub_id="")
    assert url == f"{PREFIX}?u={quote(PRODUCT, safe='')}"
    assert "subId1" not in url
    assert "partnerpropertyid" not in url
    assert "leftover" not in url
    assert url.count("?") == 1


def test_affiliate_omits_property_id_when_blank(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", PREFIX)
    monkeypatch.setattr(affiliate, "TCGPLAYER_PARTNER_PROPERTY_ID", "   ")
    url = affiliate.tcgplayer_affiliate(PRODUCT, sub_id="workshop")
    assert _keys(url) == ["subId1", "u"]
    assert "partnerpropertyid" not in url


def test_sub_id_is_sanitized(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", PREFIX)
    monkeypatch.setattr(affiliate, "TCGPLAYER_PARTNER_PROPERTY_ID", "")
    url = affiliate.tcgplayer_affiliate(PRODUCT, sub_id="blog/mill deck guide!!")
    assert dict(parse_qsl(urlparse(url).query))["subId1"] == "blog-mill-deck-guide"
    long_id = "blog-" + ("a" * 80)
    long_url = affiliate.tcgplayer_affiliate(PRODUCT, sub_id=long_id)
    sub = dict(parse_qsl(urlparse(long_url).query))["subId1"]
    assert len(sub) <= 64
    assert sub.startswith("blog-")
    bare = affiliate.tcgplayer_affiliate(PRODUCT, sub_id="!!!")
    assert bare is not None and bare.split("?", 1)[1].startswith("u=")


# Scryfall stores TCGplayer links already wrapped through its own Impact
# publisher account (partner.tcgplayer.com), with the real page in ?u=.
SCRYFALL_WRAPPED = (
    "https://partner.tcgplayer.com/c/4931599/1830156/21018?subId1=api"
    "&u=https%3A%2F%2Fwww.tcgplayer.com%2Fproduct%2F42%2Fmagic-lightning-bolt"
)


def test_affiliate_unwraps_foreign_then_rewraps(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", PREFIX)
    monkeypatch.setattr(affiliate, "TCGPLAYER_PARTNER_PROPERTY_ID", PROPERTY_ID)
    url = affiliate.tcgplayer_affiliate(SCRYFALL_WRAPPED, sub_id="workshop")
    # Must point at OUR prefix, and the inner destination must be the
    # canonical product page — not Scryfall's partner redirector.
    assert url.startswith(f"{PREFIX}?subId1=workshop&u=")
    assert _u(url) == PRODUCT
    assert "4931599" not in url
    assert "partner.tcgplayer.com" not in _u(url)
    assert url.count("?") == 1


def test_affiliate_unwraps_nested_partner_and_pxf(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", PREFIX)
    monkeypatch.setattr(affiliate, "TCGPLAYER_PARTNER_PROPERTY_ID", "")
    inner = "https://tcgplayer.pxf.io/c/1/2/3?u=" + quote(PRODUCT, safe="")
    nested = "https://partner.tcgplayer.com/c/9/9/9?subId1=other&u=" + quote(inner, safe="")
    url = affiliate.tcgplayer_affiliate(nested, sub_id="home")
    assert _u(url) == PRODUCT
    assert "4931599" not in url
    assert "/c/9/9/9" not in url
    assert "/c/1/2/3" not in url
    assert dict(parse_qsl(urlparse(url).query))["subId1"] == "home"


def test_affiliate_unwraps_to_canonical_when_unset(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", "")
    # No prefix → return the clean destination, never Scryfall's affiliate link.
    url = affiliate.tcgplayer_affiliate(SCRYFALL_WRAPPED)
    assert url == "https://www.tcgplayer.com/product/42/magic-lightning-bolt"


def test_affiliate_passthrough_empty(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", PREFIX)
    assert affiliate.tcgplayer_affiliate("") == ""
    assert affiliate.tcgplayer_affiliate(None) is None


def test_search_url_tracked(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", PREFIX)
    monkeypatch.setattr(affiliate, "TCGPLAYER_PARTNER_PROPERTY_ID", "")
    url = affiliate.tcgplayer_search_url("Ajani's Pridemate")
    assert url.startswith(f"{PREFIX}?subId1=api&u=")
    assert "Ajani" in url
    assert _u(url).startswith("https://www.tcgplayer.com/search/")


def test_ensure_link_wraps_existing(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", PREFIX)
    monkeypatch.setattr(affiliate, "TCGPLAYER_PARTNER_PROPERTY_ID", "")
    url = affiliate.ensure_tcgplayer_link(PRODUCT, "Lightning Bolt")
    assert url.startswith(f"{PREFIX}?subId1=api&u=")
    assert _u(url) == PRODUCT


def test_ensure_link_falls_back_to_search(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", "")
    url = affiliate.ensure_tcgplayer_link(None, "Opt")
    assert url.startswith("https://www.tcgplayer.com/search/magic/product")
    assert "Opt" in url


def test_mass_entry_url(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", "")
    url = affiliate.tcgplayer_mass_entry_url([("Lightning Bolt", 4), ("Island", 8)])
    assert url.startswith("https://www.tcgplayer.com/massentry")
    # Lines joined with || and quantity-prefixed, URL-encoded.
    assert "4+Lightning+Bolt" in url
    assert "%7C%7C" in url  # encoded ||
    assert "8+Island" in url


def test_mass_entry_skips_zero_qty(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", "")
    url = affiliate.tcgplayer_mass_entry_url([("Real Card", 2), ("Ghost", 0)])
    assert "Real+Card" in url
    assert "Ghost" not in url


# ── Edge cases (RP-006 / review S-7) ─────────────────────────────────────

_PRODUCT = "https://www.tcgplayer.com/product/12345/magic-lightning-bolt"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (_PRODUCT, _PRODUCT),
        (f"https://tcgplayer.pxf.io/c/1/2/3?u={quote(_PRODUCT, safe='')}", _PRODUCT),
        # Double-wrapped: Impact redirector around another redirector.
        (
            "https://partner.tcgplayer.com/c/9/9/9?u="
            + quote(f"https://tcgplayer.pxf.io/c/1/2/3?u={quote(_PRODUCT, safe='')}", safe=""),
            _PRODUCT,
        ),
        # An encoded % in the destination survives (single decode).
        (
            "https://tcgplayer.pxf.io/c/1/2/3?u=" + quote("https://www.tcgplayer.com/search?q=100%25", safe=""),
            "https://www.tcgplayer.com/search?q=100%25",
        ),
    ],
)
def test_unwraps_to_the_canonical_destination(monkeypatch, raw, expected):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", "")
    assert affiliate.tcgplayer_affiliate(raw) == expected


def test_lookalike_host_is_not_treated_as_a_redirector(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", "")
    spoof = "https://evilpxf.io.example.com/?u=" + quote(_PRODUCT, safe="")
    assert affiliate.tcgplayer_affiliate(spoof) is None


def test_non_tcgplayer_destinations_are_never_wrapped(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", "https://partner.tcgplayer.com/c/1/2/3")
    monkeypatch.setattr(affiliate, "TCGPLAYER_PARTNER_PROPERTY_ID", "")
    hostile = "https://partner.tcgplayer.com/c/1/2/3?u=" + quote("https://evil.example.com/phish", safe="")
    assert affiliate.tcgplayer_affiliate(hostile) is None
    link = affiliate.ensure_tcgplayer_link(hostile, "Lightning Bolt")
    assert link.startswith("https://partner.tcgplayer.com/c/1/2/3?subId1=api&u=")
    assert "evil.example.com" not in link and "tcgplayer.com%2Fsearch" in link
    assert _u(link).startswith("https://www.tcgplayer.com/search/")


def test_redirector_without_destination_is_refused(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", "")
    assert affiliate.tcgplayer_affiliate("https://partner.tcgplayer.com/c/9/9/9?subId1=api") is None
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", PREFIX)
    assert affiliate.tcgplayer_affiliate("https://tcgplayer.pxf.io/c/1/2/3") is None


def test_unwrap_is_bounded():
    url = _PRODUCT
    for _ in range(12):
        url = "https://tcgplayer.pxf.io/c/1/2/3?u=" + quote(url, safe="")
    # Still a redirector after five layers: returned as-is, never loops.
    assert affiliate._canonical_destination(url).startswith("https://tcgplayer.pxf.io/")


def test_wrapping_our_own_link_is_idempotent(monkeypatch):
    prefix = "https://partner.tcgplayer.com/c/1/2/3"
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", prefix)
    monkeypatch.setattr(affiliate, "TCGPLAYER_PARTNER_PROPERTY_ID", PROPERTY_ID)
    once = affiliate.tcgplayer_affiliate(_PRODUCT, sub_id="api")
    assert affiliate.tcgplayer_affiliate(once, sub_id="api") == once
    # Re-wrapping with a page tag replaces subId1; it does not nest another u=.
    page = affiliate.tcgplayer_affiliate(once, sub_id="workshop")
    assert page.startswith(f"{prefix}?subId1=workshop&u=")
    assert _u(page) == _PRODUCT
    assert page.count("u=") == 1
