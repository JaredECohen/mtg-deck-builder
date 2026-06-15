"""TCGplayer affiliate link construction.

All TCGplayer purchase URLs flow through here so affiliate attribution is
applied in exactly one place. TCGplayer runs its affiliate program through
Impact (impact.com), which issues a per-publisher "deep link" prefix of the
form ``https://tcgplayer.pxf.io/c/<pubId>/<campaignId>/<mediaId>``. A tracked
link is that prefix plus ``?u=<url-encoded destination>``.

Set ``TCGPLAYER_AFFILIATE_URL`` to your Impact deep-link prefix. When unset,
plain (untracked) TCGplayer links are produced so the app works out of the
box during development.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from app.config import TCGPLAYER_AFFILIATE_URL

_SEARCH_BASE = "https://www.tcgplayer.com/search/magic/product"
_MASS_ENTRY_BASE = "https://www.tcgplayer.com/massentry"

# Impact-style affiliate redirector hosts. Scryfall's stored TCGplayer links
# already point through one of these (Scryfall's own publisher account),
# wrapping the real destination in a ``u=`` param. We must unwrap to the
# canonical destination before re-wrapping with our own prefix, otherwise
# attribution chains through the original affiliate.
_AFFILIATE_HOSTS = ("pxf.io", "partner.tcgplayer.com")


def _canonical_destination(url: str) -> str:
    """Strip any Impact-style affiliate wrapper, returning the innermost
    real destination URL."""
    for _ in range(5):  # bounded unwrap to avoid pathological loops
        parsed = urlparse(url)
        if not any(host in parsed.netloc for host in _AFFILIATE_HOSTS):
            return url
        inner = parse_qs(parsed.query).get("u", [None])[0]
        if not inner:
            return url
        url = unquote(inner)
    return url


def tcgplayer_affiliate(destination_url: str | None) -> str | None:
    """Return an affiliate-tracked TCGplayer link.

    Unwraps any pre-existing affiliate redirector to the canonical
    destination, then re-wraps with our Impact deep link when a publisher
    prefix is configured. With no prefix configured, returns the clean
    canonical destination (never another party's affiliate link).
    """
    if not destination_url:
        return destination_url
    canonical = _canonical_destination(destination_url)
    if not TCGPLAYER_AFFILIATE_URL:
        return canonical
    return f"{TCGPLAYER_AFFILIATE_URL}?u={quote_plus(canonical)}"


def tcgplayer_search_url(card_name: str) -> str:
    """Affiliate-tracked TCGplayer search URL for a single card."""
    dest = f"{_SEARCH_BASE}?q={quote_plus(card_name)}&productLineName=magic"
    return tcgplayer_affiliate(dest) or dest


def ensure_tcgplayer_link(url: str | None, card_name: str) -> str:
    """Return an affiliate-tracked TCGplayer link for a card: wrap the
    card's own product URL when present, else fall back to a tracked
    search URL built from its name.
    """
    if url:
        return tcgplayer_affiliate(url) or url
    return tcgplayer_search_url(card_name)


def tcgplayer_mass_entry_url(entries: Iterable[tuple[str, int]]) -> str:
    """Affiliate-tracked TCGplayer Mass Entry URL for a whole decklist.

    ``entries`` is an iterable of ``(card_name, quantity)``. Mass Entry
    builds a single cart pre-filled with every card, optimized to the
    cheapest available sellers — the highest-converting surface for a
    deck builder.
    """
    lines = "||".join(f"{qty} {name}" for name, qty in entries if name and qty > 0)
    dest = f"{_MASS_ENTRY_BASE}?productline=Magic&c={quote_plus(lines)}"
    return tcgplayer_affiliate(dest) or dest
