"""
Tests de résilience du collecteur RSS.
Aucun appel réseau réel : httpx.get est mocké. Vérifie qu'une source en échec
n'empêche jamais la collecte des autres, et que les tentatives de retry
respectent la configuration sans jamais lever d'exception vers l'appelant.
"""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import httpx
import pytest

from app.collectors import rss_collector
from app.publishers.formatter import build_discord_embed, extract_cvss_from_text
from app.collectors.sources import SOURCES


VALID_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Source test</title>
<item>
  <title>Alerte test CVE-2026-11111</title>
  <link>https://example.org/alerte-1</link>
  <description>CVSS: 9.5 exploitation confirmee</description>
</item>
</channel></rss>""".encode("utf-8")


def test_is_safe_url_rejects_non_http_schemes():
    assert rss_collector._is_safe_url("https://example.org/feed") is True
    assert rss_collector._is_safe_url("ftp://example.org/feed") is False
    assert rss_collector._is_safe_url("file:///etc/passwd") is False
    assert rss_collector._is_safe_url("not-a-url") is False


def test_collect_all_isolates_failing_source(monkeypatch):
    """
    Une source qui échoue systématiquement (timeout) ne doit pas empêcher
    la collecte des entrées d'une autre source qui répond normalement.
    """
    sources = [
        {"name": "SourceEnPanne", "url": "https://panne.example.org/feed"},
        {"name": "SourceOK", "url": "https://ok.example.org/feed"},
    ]
    monkeypatch.setattr(rss_collector, "SOURCES", sources)
    monkeypatch.setattr(rss_collector.settings, "rss_fetch_max_retries", 0)

    def fake_get(url, **kwargs):
        if "panne" in url:
            raise httpx.TimeoutException("simulated timeout")
        response = MagicMock()
        response.content = VALID_RSS
        response.raise_for_status = MagicMock()
        return response

    with patch("app.collectors.rss_collector.httpx.get", side_effect=fake_get), \
         patch("app.collectors.rss_collector.time.sleep"):
        entries = rss_collector.collect_all()

    assert len(entries) == 1
    assert entries[0]["source"] == "SourceOK"
    assert "CVE-2026-11111" in entries[0]["title"]


def test_collect_all_never_raises_on_totally_unexpected_error(monkeypatch):
    """Filet de sécurité : même une exception totalement imprévue sur une source ne remonte jamais."""
    sources = [{"name": "SourceCassee", "url": "https://cassee.example.org/feed"}]
    monkeypatch.setattr(rss_collector, "SOURCES", sources)

    with patch("app.collectors.rss_collector._collect_source", side_effect=RuntimeError("boom")):
        entries = rss_collector.collect_all()  # ne doit pas lever d'exception

    assert entries == []


def test_fetch_feed_bytes_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(rss_collector.settings, "rss_fetch_max_retries", 2)

    call_count = {"n": 0}

    def fake_get(url, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise httpx.TimeoutException("simulated timeout")
        response = MagicMock()
        response.content = VALID_RSS
        response.raise_for_status = MagicMock()
        return response

    with patch("app.collectors.rss_collector.httpx.get", side_effect=fake_get), \
         patch("app.collectors.rss_collector.time.sleep"):
        result = rss_collector._fetch_feed_bytes("SourceTest", "https://example.org/feed")

    assert result == VALID_RSS
    assert call_count["n"] == 2


def test_fetch_feed_bytes_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(rss_collector.settings, "rss_fetch_max_retries", 1)

    with patch("app.collectors.rss_collector.httpx.get", side_effect=httpx.TimeoutException("x")), \
         patch("app.collectors.rss_collector.time.sleep"):
        result = rss_collector._fetch_feed_bytes("SourceTest", "https://example.org/feed")

    assert result is None


def test_fetch_feed_uses_browser_headers():
    response = MagicMock()
    response.headers = {}
    response.content = VALID_RSS
    response.url = "https://example.org/feed"
    response.raise_for_status = MagicMock()

    with patch("app.collectors.rss_collector.httpx.get", return_value=response) as get:
        assert rss_collector._fetch_feed_bytes("SourceTest", "https://example.org/feed") == VALID_RSS

    headers = get.call_args.kwargs["headers"]
    assert headers["User-Agent"].startswith("Mozilla/5.0")
    assert headers["Accept"] == "application/rss+xml, application/xml, text/xml, */*"


def test_configured_sources_use_updated_feed_urls():
    urls = {source["name"]: source["url"] for source in SOURCES}
    assert urls["GitHub Security Advisories"] == "https://github.com/advisories.atom"
    assert urls["Ars Technica — Security"] == "https://feeds.arstechnica.com/arstechnica/security"
    assert urls["Cisco Talos"] == "https://blog.talosintelligence.com/rss/"
    assert urls["CISA KEV"] == "https://www.cisa.gov/known-exploited-vulnerabilities-catalog.xml"
    assert urls["Microsoft Security"] == "https://api.msrc.microsoft.com/cvrf/v2.0/atom"


def test_rss_native_image_is_carried_to_discord_embed():
    article = {
        "title": "Alerte",
        "source": "RSS",
        "source_url": "https://example.org/article",
        "image_url": "https://cdn.example.org/image.jpg",
        "urgency": "urgent",
    }
    payload = build_discord_embed(article, "Texte rédigé en français")
    assert payload["embeds"][0]["image"]["url"] == article["image_url"]


def test_discord_embed_has_no_image_without_rss_image():
    article = {
        "title": "Alerte",
        "source": "RSS",
        "source_url": "https://example.org/article",
        "urgency": "urgent",
    }
    assert "image" not in build_discord_embed(article, "Texte rédigé en français")["embeds"][0]


def test_extract_image_from_media_content():
    entry = SimpleNamespace(
        media_content=[{"url": "https://cdn.example.org/content.jpg", "type": "image/jpeg"}],
        media_thumbnail=[],
        enclosures=[],
        summary="",
    )
    assert rss_collector._extract_image_url(entry) == "https://cdn.example.org/content.jpg"


def test_extract_image_from_media_thumbnail():
    entry = SimpleNamespace(
        media_content=[],
        media_thumbnail=[{"url": "https://cdn.example.org/thumb.jpg", "type": "image/jpeg"}],
        enclosures=[],
        summary="",
    )
    assert rss_collector._extract_image_url(entry) == "https://cdn.example.org/thumb.jpg"


def test_extract_image_from_image_enclosure():
    entry = SimpleNamespace(
        media_content=[],
        media_thumbnail=[],
        enclosures=[{"href": "https://cdn.example.org/enclosure.png", "type": "image/png"}],
        summary="",
    )
    assert rss_collector._extract_image_url(entry) == "https://cdn.example.org/enclosure.png"


def test_extract_image_from_html_summary():
    entry = SimpleNamespace(
        media_content=[],
        media_thumbnail=[],
        enclosures=[],
        summary='<p>Résumé</p><img src="https://cdn.example.org/summary.webp" alt="illustration">',
    )
    assert rss_collector._extract_image_url(entry) == "https://cdn.example.org/summary.webp"


def test_extract_image_returns_none_when_entry_has_no_image():
    entry = SimpleNamespace(media_content=[], media_thumbnail=[], enclosures=[], summary="Résumé sans image")
    assert rss_collector._extract_image_url(entry) is None


def test_cvss_is_extracted_from_source_summary_when_article_score_is_missing():
    article = {
        "title": "Chrome V8 zero-day",
        "source": "RSS",
        "source_url": "https://example.org/article",
        "raw_summary": "Correctif publié pour une faille CVSS score: 8.8.",
        "cvss_score": None,
    }
    assert extract_cvss_from_text("CVSS score: 8.8") == "8.8"
    assert extract_cvss_from_text("CVSS: 8.8") == "8.8"
    fields = build_discord_embed(article, None)["embeds"][0]["fields"]
    assert fields[1]["value"] == "8.8"
