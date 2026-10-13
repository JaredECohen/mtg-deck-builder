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
from urllib.parse import parse_qs, quote_plus, urlparse

from app.config import TCGPLAYER_AFFILIATE_URL

_SEARCH_BASE = "https://www.tcgplayer.com/search/magic/product"
_MASS_ENTRY_BASE = "https://www.tcgplayer.com/massentry"

# Impact-style affiliate redirector hosts. Scryfall's stored TCGplayer links
# already point through one of these (Scryfall's own publisher account),
# wrapping the real destination in a ``u=`` param. We must unwrap to the
# canonical destination before re-wrapping with our own prefix, otherwise
# attribution chains through the original affiliate.
_AFFILIATE_HOSTS = ("pxf.io", "partner.tcgplayer.com")
_MAX_UNWRAP = 5


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _host_is(host: str, domain: str) -> bool:
    """Exact domain or a subdomain of it ("tcgplayer.pxf.io" is pxf.io;
    "evilpxf.io.example.com" is not)."""
    return host == domain or host.endswith("." + domain)


def _is_redirector(url: str) -> bool:
    return any(_host_is(_host(url), domain) for domain in _AFFILIATE_HOSTS)


def is_tcgplayer_url(url: str) -> bool:
    return urlparse(url).scheme in {"http", "https"} and _host_is(_host(url), "tcgplayer.com")


def _canonical_destination(url: str) -> str:
    """Strip any Impact-style affiliate wrapper, returning the innermost
    real destination URL (at most five layers deep)."""
    for _ in range(_MAX_UNWRAP):
        if not _is_redirector(url):
            return url
        # parse_qs already percent-decodes; decoding again would corrupt
        # destinations containing an encoded "%".
        inner = parse_qs(urlparse(url).query).get("u", [None])[0]
        if not inner:
            return url
        url = inner
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
    if not is_tcgplayer_url(canonical):
        # Never wrap (or pass through) a non-TCGplayer destination: a
        # crafted u= parameter must not turn our buy button into a redirect.
        return None
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
        wrapped = tcgplayer_affiliate(url)
        if wrapped:
            return wrapped
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
