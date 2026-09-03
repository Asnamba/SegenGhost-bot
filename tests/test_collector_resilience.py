"""
Tests de résilience du collecteur RSS.
Aucun appel réseau réel : httpx.get est mocké. Vérifie qu'une source en échec
n'empêche jamais la collecte des autres, et que les tentatives de retry
respectent la configuration sans jamais lever d'exception vers l'appelant.
"""
from unittest.mock import patch, MagicMock

import httpx
import pytest

from app.collectors import rss_collector


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
