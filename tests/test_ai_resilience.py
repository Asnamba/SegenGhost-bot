"""
Tests de résilience du module de rédaction IA.
Aucun appel réseau réel : le client Anthropic est entièrement mocké.
Vérifie la garantie centrale : une erreur d'API ne doit JAMAIS remonter
comme exception jusqu'à l'appelant (le pipeline) — toujours un retour None.
"""
from unittest.mock import patch, MagicMock

import anthropic
import pytest

from app.ai import rewriter


ARTICLE = {
    "title": "Faille critique sur un pare-feu",
    "source": "CISA",
    "source_url": "https://example.org/advisory",
    "cve_id": "CVE-2026-99999",
    "cvss_score": 9.4,
    "exploited": True,
    "category": "vulnerabilite",
    "region": None,
    "raw_summary": "Résumé brut factuel.",
}


def _fake_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


@pytest.fixture(autouse=True)
def reset_client():
    rewriter._client = None
    yield
    rewriter._client = None


def test_rewrite_urgent_returns_none_when_no_api_key(monkeypatch):
    monkeypatch.setattr(rewriter.settings, "anthropic_api_key", "")
    assert rewriter.rewrite_urgent(ARTICLE) is None


def test_rewrite_urgent_success_path(monkeypatch):
    monkeypatch.setattr(rewriter.settings, "anthropic_api_key", "fake-key")
    valid_text = "🚨 ALERTE CRITIQUE — CVE-2026-99999 ... CVSS 9.4 ..."

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(valid_text)

    with patch.object(rewriter, "_get_client", return_value=fake_client):
        result = rewriter.rewrite_urgent(ARTICLE)

    assert result == valid_text


def test_rewrite_urgent_blocked_when_cve_altered(monkeypatch):
    """Le texte généré ne contient pas le CVE d'origine : doit être bloqué (retour None)."""
    monkeypatch.setattr(rewriter.settings, "anthropic_api_key", "fake-key")
    invalid_text = "🚨 ALERTE — une faille critique a été détectée, sans identifiant précis."

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(invalid_text)

    with patch.object(rewriter, "_get_client", return_value=fake_client):
        result = rewriter.rewrite_urgent(ARTICLE)

    assert result is None


def test_rewrite_urgent_handles_timeout_without_raising(monkeypatch):
    """Une erreur de timeout API ne doit jamais lever d'exception jusqu'à l'appelant."""
    monkeypatch.setattr(rewriter.settings, "anthropic_api_key", "fake-key")
    monkeypatch.setattr(rewriter.settings, "ai_max_retries", 0)

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = anthropic.APITimeoutError(request=MagicMock())

    with patch.object(rewriter, "_get_client", return_value=fake_client), \
         patch("app.ai.rewriter.time.sleep"):
        result = rewriter.rewrite_urgent(ARTICLE)  # ne doit PAS lever d'exception

    assert result is None


def test_rewrite_urgent_handles_unexpected_exception_without_raising(monkeypatch):
    """Filet de sécurité : même une erreur totalement imprévue reste contenue."""
    monkeypatch.setattr(rewriter.settings, "anthropic_api_key", "fake-key")

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("erreur imprévue")

    with patch.object(rewriter, "_get_client", return_value=fake_client):
        result = rewriter.rewrite_urgent(ARTICLE)

    assert result is None


def test_rewrite_digest_item_empty_response_is_rejected(monkeypatch):
    monkeypatch.setattr(rewriter.settings, "anthropic_api_key", "fake-key")

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response("")

    with patch.object(rewriter, "_get_client", return_value=fake_client):
        result = rewriter.rewrite_digest_item(ARTICLE)

    assert result is None
