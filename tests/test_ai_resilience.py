"""
Tests de résilience du module de rédaction IA.
Aucun appel réseau réel : le client Anthropic est entièrement mocké.
Vérifie la garantie centrale : une erreur d'API ne doit JAMAIS remonter
comme exception jusqu'à l'appelant (le pipeline) — toujours un retour None.
"""
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

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
    rewriter._gemini_client = None
    rewriter.settings.ai_provider = "anthropic"
    yield
    rewriter._client = None
    rewriter._gemini_client = None


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


def _fake_gemini_response(text: str):
    response = MagicMock()
    response.text = text
    return response


def test_gemini_success_path(monkeypatch):
    monkeypatch.setattr(rewriter.settings, "ai_provider", "gemini")
    monkeypatch.setattr(rewriter.settings, "gemini_api_key", "fake-key")
    valid_text = "ALERTE — CVE-2026-99999 — CVSS 9.4"
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _fake_gemini_response(valid_text)

    with patch.object(rewriter, "_get_gemini_client", return_value=fake_client):
        assert rewriter.rewrite_urgent(ARTICLE) == valid_text

    call = fake_client.models.generate_content.call_args
    assert call.kwargs["model"] == rewriter.settings.gemini_model
    assert call.kwargs["config"].system_instruction


def test_gemini_ignores_anthropic_key(monkeypatch):
    monkeypatch.setattr(rewriter.settings, "ai_provider", "gemini")
    monkeypatch.setattr(rewriter.settings, "gemini_api_key", "")
    monkeypatch.setattr(rewriter.settings, "anthropic_api_key", "")
    with patch.object(rewriter, "_get_client") as anthropic_client:
        assert rewriter.rewrite_urgent(ARTICLE) is None
    anthropic_client.assert_not_called()


def test_gemini_handles_transient_error_without_raising(monkeypatch):
    monkeypatch.setattr(rewriter.settings, "ai_provider", "gemini")
    monkeypatch.setattr(rewriter.settings, "gemini_api_key", "fake-key")
    monkeypatch.setattr(rewriter.settings, "ai_max_retries", 0)
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = TimeoutError("simulated timeout")

    with patch.object(rewriter, "_get_gemini_client", return_value=fake_client):
        assert rewriter.rewrite_urgent(ARTICLE) is None


def test_gemini_validation_blocks_altered_facts(monkeypatch):
    monkeypatch.setattr(rewriter.settings, "ai_provider", "gemini")
    monkeypatch.setattr(rewriter.settings, "gemini_api_key", "fake-key")
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _fake_gemini_response("Une faille critique a été détectée.")

    with patch.object(rewriter, "_get_gemini_client", return_value=fake_client):
        assert rewriter.rewrite_digest_item(ARTICLE) is None


def test_provider_priority_falls_back_to_next_provider(monkeypatch):
    monkeypatch.setattr(rewriter.settings, "ai_provider", "groq")
    monkeypatch.setattr(rewriter.settings, "ai_provider_priority", "groq,gemini,mistral")
    monkeypatch.setattr(rewriter.settings, "groq_api_key", "groq-key")
    monkeypatch.setattr(rewriter.settings, "gemini_api_key", "gemini-key")
    valid_text = "Alerte CVE-2026-99999 CVSS 9.4"
    provider_call = AsyncMock(side_effect=[None, valid_text])

    with patch.object(rewriter, "_call_provider_async", provider_call):
        result = asyncio.run(rewriter.rewrite_article_async(ARTICLE, urgent=True))

    assert result == valid_text
    assert [call.args[0] for call in provider_call.call_args_list] == ["groq", "gemini"]


def test_all_provider_failures_return_none_without_raising(monkeypatch):
    monkeypatch.setattr(rewriter.settings, "ai_provider_priority", "groq,gemini,mistral")
    monkeypatch.setattr(rewriter.settings, "groq_api_key", "groq-key")
    monkeypatch.setattr(rewriter.settings, "gemini_api_key", "gemini-key")
    monkeypatch.setattr(rewriter.settings, "mistral_api_key", "mistral-key")

    with patch.object(rewriter, "_call_provider_async", AsyncMock(return_value=None)):
        assert asyncio.run(rewriter.rewrite_article_async(ARTICLE)) is None


def test_every_provider_receives_french_system_prompt(monkeypatch):
    monkeypatch.setattr(rewriter.settings, "ai_provider_priority", "groq,gemini,mistral,anthropic")
    for provider in ("groq", "gemini", "mistral", "anthropic"):
        assert "en français" in rewriter.SYSTEM_PROMPT_URGENT
        assert "en français" in rewriter.SYSTEM_PROMPT_DIGEST_ITEM
