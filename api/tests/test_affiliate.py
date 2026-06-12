"""Amazon affiliate link construction."""

from app.services import affiliate


def test_amazon_search_url_untagged(monkeypatch):
    monkeypatch.setattr(affiliate, "AMAZON_AFFILIATE_TAG", "")
    url = affiliate.amazon_search_url("Lightning Bolt")
    assert url.startswith("https://www.amazon.com/s?k=Lightning+Bolt")
    assert "tag=" not in url


def test_amazon_search_url_tagged(monkeypatch):
    monkeypatch.setattr(affiliate, "AMAZON_AFFILIATE_TAG", "mydecksite-20")
    url = affiliate.amazon_search_url("Ajani's Pridemate")
    assert "tag=mydecksite-20" in url
    assert "Ajani%27s+Pridemate" in url


def test_ensure_affiliate_tag_appends_to_existing_url(monkeypatch):
    monkeypatch.setattr(affiliate, "AMAZON_AFFILIATE_TAG", "mydecksite-20")
    url = affiliate.ensure_affiliate_tag("https://www.amazon.com/s?k=Opt+mtg", "Opt")
    assert url == "https://www.amazon.com/s?k=Opt+mtg&tag=mydecksite-20"


def test_ensure_affiliate_tag_does_not_double_tag(monkeypatch):
    monkeypatch.setattr(affiliate, "AMAZON_AFFILIATE_TAG", "mydecksite-20")
    tagged = "https://www.amazon.com/s?k=Opt+mtg&tag=other-21"
    assert affiliate.ensure_affiliate_tag(tagged, "Opt") == tagged


def test_ensure_affiliate_tag_builds_fresh_url_when_missing(monkeypatch):
    monkeypatch.setattr(affiliate, "AMAZON_AFFILIATE_TAG", "")
    url = affiliate.ensure_affiliate_tag(None, "Opt")
    assert url.startswith("https://www.amazon.com/s?k=Opt")
