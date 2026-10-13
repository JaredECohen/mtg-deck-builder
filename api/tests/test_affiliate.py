"""TCGplayer affiliate link construction."""

from app.services import affiliate

PREFIX = "https://tcgplayer.pxf.io/c/123456/789012/21018"
PRODUCT = "https://www.tcgplayer.com/product/42/magic-lightning-bolt"


def test_affiliate_unset_returns_destination(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", "")
    assert affiliate.tcgplayer_affiliate(PRODUCT) == PRODUCT


def test_affiliate_wraps_destination(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", PREFIX)
    url = affiliate.tcgplayer_affiliate(PRODUCT)
    assert url.startswith(f"{PREFIX}?u=")
    # Destination is URL-encoded inside the u= param.
    assert "www.tcgplayer.com" not in url.split("?u=")[0]
    assert "tcgplayer.com%2Fproduct" in url


# Scryfall stores TCGplayer links already wrapped through its own Impact
# publisher account (partner.tcgplayer.com), with the real page in ?u=.
SCRYFALL_WRAPPED = (
    "https://partner.tcgplayer.com/c/4931599/1830156/21018?subId1=api"
    "&u=https%3A%2F%2Fwww.tcgplayer.com%2Fproduct%2F42%2Fmagic-lightning-bolt"
)


def test_affiliate_unwraps_foreign_then_rewraps(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", PREFIX)
    url = affiliate.tcgplayer_affiliate(SCRYFALL_WRAPPED)
    # Must point at OUR prefix, and the inner destination must be the
    # canonical product page — not Scryfall's partner redirector.
    assert url.startswith(f"{PREFIX}?u=")
    assert "partner.tcgplayer.com" not in url
    assert "4931599" not in url
    assert "product%2F42" in url


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
    url = affiliate.tcgplayer_search_url("Ajani's Pridemate")
    assert url.startswith(f"{PREFIX}?u=")
    assert "Ajani" in url


def test_ensure_link_wraps_existing(monkeypatch):
    monkeypatch.setattr(affiliate, "TCGPLAYER_AFFILIATE_URL", PREFIX)
    url = affiliate.ensure_tcgplayer_link(PRODUCT, "Lightning Bolt")
    assert url.startswith(f"{PREFIX}?u=")


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

import pytest  # noqa: E402

from app.services import affiliate as affiliate_module  # noqa: E402

_PRODUCT = "https://www.tcgplayer.com/product/12345/magic-lightning-bolt"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (_PRODUCT, _PRODUCT),
        (f"https://tcgplayer.pxf.io/c/1/2/3?u={affiliate_module.quote_plus(_PRODUCT)}", _PRODUCT),
        # Double-wrapped: Impact redirector around another redirector.
        (
            "https://partner.tcgplayer.com/c/9/9/9?u="
            + affiliate_module.quote_plus(f"https://tcgplayer.pxf.io/c/1/2/3?u={affiliate_module.quote_plus(_PRODUCT)}"),
            _PRODUCT,
        ),
        # An encoded % in the destination survives (single decode).
        (
            "https://tcgplayer.pxf.io/c/1/2/3?u=" + affiliate_module.quote_plus("https://www.tcgplayer.com/search?q=100%25"),
            "https://www.tcgplayer.com/search?q=100%25",
        ),
    ],
)
def test_unwraps_to_the_canonical_destination(monkeypatch, raw, expected):
    monkeypatch.setattr(affiliate_module, "TCGPLAYER_AFFILIATE_URL", "")
    assert affiliate_module.tcgplayer_affiliate(raw) == expected


def test_lookalike_host_is_not_treated_as_a_redirector(monkeypatch):
    monkeypatch.setattr(affiliate_module, "TCGPLAYER_AFFILIATE_URL", "")
    spoof = "https://evilpxf.io.example.com/?u=" + affiliate_module.quote_plus(_PRODUCT)
    assert affiliate_module.tcgplayer_affiliate(spoof) is None


def test_non_tcgplayer_destinations_are_never_wrapped(monkeypatch):
    monkeypatch.setattr(affiliate_module, "TCGPLAYER_AFFILIATE_URL", "https://tcgplayer.pxf.io/c/1/2/3")
    hostile = "https://tcgplayer.pxf.io/c/1/2/3?u=" + affiliate_module.quote_plus("https://evil.example.com/phish")
    assert affiliate_module.tcgplayer_affiliate(hostile) is None
    link = affiliate_module.ensure_tcgplayer_link(hostile, "Lightning Bolt")
    assert link.startswith("https://tcgplayer.pxf.io/c/1/2/3?u=")
    assert "evil.example.com" not in link and "tcgplayer.com%2Fsearch" in link


def test_unwrap_is_bounded():
    url = _PRODUCT
    for _ in range(12):
        url = "https://tcgplayer.pxf.io/c/1/2/3?u=" + affiliate_module.quote_plus(url)
    # Still a redirector after five layers: returned as-is, never loops.
    assert affiliate_module._canonical_destination(url).startswith("https://tcgplayer.pxf.io/")


def test_wrapping_our_own_link_is_idempotent(monkeypatch):
    prefix = "https://tcgplayer.pxf.io/c/1/2/3"
    monkeypatch.setattr(affiliate_module, "TCGPLAYER_AFFILIATE_URL", prefix)
    once = affiliate_module.tcgplayer_affiliate(_PRODUCT)
    assert affiliate_module.tcgplayer_affiliate(once) == once
