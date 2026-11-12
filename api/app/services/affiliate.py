"""TCGplayer affiliate link construction.

All TCGplayer purchase URLs flow through here so affiliate attribution is
applied in exactly one place. TCGplayer runs its affiliate program through
Impact (impact.com). A tracked link is the publisher deep-link prefix plus
a query string in Impact's order:

    {prefix}?subId1={page}&u={urlencoded destination}&partnerpropertyid={id}

``subId1`` and ``partnerpropertyid`` are omitted when empty. ``u`` is the
fully encoded canonical tcgplayer.com URL. Any ``pxf.io`` or
``partner.tcgplayer.com`` wrapper is unwrapped first, so a stored Scryfall
affiliate link is never chained and a link is never double-wrapped.

Set ``TCGPLAYER_AFFILIATE_URL`` to the prefix only (no query string), for
example ``https://partner.tcgplayer.com/c/123456/789012/21018``. Set
``TCGPLAYER_PARTNER_PROPERTY_ID`` to append ``partnerpropertyid``. When the
prefix is unset, plain (untracked) tcgplayer.com links are produced.

``subId1`` values are short and URL-safe (letters, digits, ``-``, ``_``,
at most 64 characters). This module's own wrap uses ``api``. Pages re-wrap
with their own tag (``home``, ``workshop``, ``workshop-precon``,
``blog-<slug>``) before the link is shown.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import parse_qs, quote, quote_plus, urlparse, urlunparse

from app.config import TCGPLAYER_AFFILIATE_URL, TCGPLAYER_PARTNER_PROPERTY_ID

_SEARCH_BASE = "https://www.tcgplayer.com/search/magic/product"
_MASS_ENTRY_BASE = "https://www.tcgplayer.com/massentry"

# Impact-style affiliate redirector hosts. Scryfall's stored TCGplayer links
# already point through one of these (Scryfall's own publisher account),
# wrapping the real destination in a ``u=`` param. We must unwrap to the
# canonical destination before re-wrapping with our own prefix, otherwise
# attribution chains through the original affiliate.
_AFFILIATE_HOSTS = ("pxf.io", "partner.tcgplayer.com")
_MAX_UNWRAP = 5
_MAX_SUB_ID = 64
# Fallback when the API wraps a link itself. The browser re-wraps with the
# page tag before display; this remains for clients that use the URL as-is.
API_SUB_ID = "api"
_UNSAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")
_REPEATED_HYPHEN = re.compile(r"-{2,}")


def sanitize_sub_id(sub_id: str | None) -> str:
    """Impact subId1: letters, digits, hyphen, underscore, at most 64 chars."""
    if not sub_id:
        return ""
    cleaned = _UNSAFE_ID.sub("-", sub_id.strip())
    cleaned = _REPEATED_HYPHEN.sub("-", cleaned).strip("-_")
    return cleaned[:_MAX_SUB_ID].strip("-_")


def _sanitize_property_id(property_id: str | None) -> str:
    if not property_id:
        return ""
    return _UNSAFE_ID.sub("", property_id.strip())


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


def _affiliate_prefix() -> str:
    """Deep-link prefix with any pasted query or fragment removed."""
    raw = (TCGPLAYER_AFFILIATE_URL or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


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


def _tracked_url(canonical: str, sub_id: str | None) -> str:
    """Assemble Impact's query order: subId1, u, partnerpropertyid."""
    prefix = _affiliate_prefix()
    params: list[str] = []
    safe_sub = sanitize_sub_id(sub_id)
    if safe_sub:
        params.append(f"subId1={quote(safe_sub, safe='')}")
    params.append(f"u={quote(canonical, safe='')}")
    property_id = _sanitize_property_id(TCGPLAYER_PARTNER_PROPERTY_ID)
    if property_id:
        params.append(f"partnerpropertyid={quote(property_id, safe='')}")
    separator = "&" if "?" in prefix else "?"
    return f"{prefix}{separator}{'&'.join(params)}"


def tcgplayer_affiliate(destination_url: str | None, sub_id: str | None = API_SUB_ID) -> str | None:
    """Return an affiliate-tracked TCGplayer link.

    Unwraps any pre-existing affiliate redirector to the canonical
    destination, then re-wraps with our Impact deep link when a publisher
    prefix is configured. With no prefix configured, returns the clean
    canonical destination (never another party's affiliate link). A
    destination that is not tcgplayer.com — or that is still a redirector
    after unwrapping — is refused.
    """
    if not destination_url:
        return destination_url
    canonical = _canonical_destination(destination_url)
    if _is_redirector(canonical) or not is_tcgplayer_url(canonical):
        # Never wrap (or pass through) a non-TCGplayer destination, and
        # never leave another publisher's redirector in place. A crafted
        # u= parameter must not turn our buy button into an open redirect.
        return None
    if not _affiliate_prefix():
        return canonical
    return _tracked_url(canonical, sub_id)


def tcgplayer_search_url(card_name: str, sub_id: str | None = API_SUB_ID) -> str:
    """Affiliate-tracked TCGplayer search URL for a single card."""
    dest = f"{_SEARCH_BASE}?q={quote_plus(card_name)}&productLineName=magic"
    return tcgplayer_affiliate(dest, sub_id=sub_id) or dest


def ensure_tcgplayer_link(url: str | None, card_name: str, sub_id: str | None = API_SUB_ID) -> str:
    """Return an affiliate-tracked TCGplayer link for a card: wrap the
    card's own product URL when present, else fall back to a tracked
    search URL built from its name.
    """
    if url:
        wrapped = tcgplayer_affiliate(url, sub_id=sub_id)
        if wrapped:
            return wrapped
    return tcgplayer_search_url(card_name, sub_id=sub_id)


def tcgplayer_mass_entry_url(
    entries: Iterable[tuple[str, int]],
    sub_id: str | None = API_SUB_ID,
) -> str:
    """Affiliate-tracked TCGplayer Mass Entry URL for a whole decklist.

    ``entries`` is an iterable of ``(card_name, quantity)``. Mass Entry
    builds a single cart pre-filled with every card, optimized to the
    cheapest available sellers — the highest-converting surface for a
    deck builder.
    """
    lines = "||".join(f"{qty} {name}" for name, qty in entries if name and qty > 0)
    dest = f"{_MASS_ENTRY_BASE}?productline=Magic&c={quote_plus(lines)}"
    return tcgplayer_affiliate(dest, sub_id=sub_id) or dest
