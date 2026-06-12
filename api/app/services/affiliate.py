"""Amazon affiliate link construction.

All Amazon purchase URLs flow through here so the Associates tag is
applied in exactly one place. The tag comes from the AMAZON_AFFILIATE_TAG
environment variable; when unset, plain (untagged) search links are
produced so the app works out of the box.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from app.config import AMAZON_AFFILIATE_TAG


def amazon_search_url(card_name: str) -> str:
    """Build an Amazon search URL for a card, tagged when configured."""
    url = f"https://www.amazon.com/s?k={quote_plus(card_name)}+magic+the+gathering+card"
    if AMAZON_AFFILIATE_TAG:
        url += f"&tag={quote_plus(AMAZON_AFFILIATE_TAG)}"
    return url


def ensure_affiliate_tag(url: str | None, card_name: str) -> str:
    """Return ``url`` with the affiliate tag appended, or a fresh tagged
    search URL when ``url`` is empty. Links that already carry a tag are
    left untouched (re-ingested data may have been tagged at write time).
    """
    if not url:
        return amazon_search_url(card_name)
    if AMAZON_AFFILIATE_TAG and "tag=" not in url:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}tag={quote_plus(AMAZON_AFFILIATE_TAG)}"
    return url
