"""
Tests de résilience des publishers Discord/Telegram.
Aucun appel réseau réel. Vérifie :
- le retry sur erreurs transitoires (429, 5xx, timeout) ;
- l'abandon propre (retour False, jamais d'exception) sur échec persistant ;
- l'ABSENCE de tout secret (token) dans les messages de log, même en cas d'erreur.
"""
import logging
from unittest.mock import patch, MagicMock

import httpx

from app.publishers import http_utils, discord_bot, discord_publisher, telegram_publisher


def _mock_response(status_code: int):
    response = MagicMock()
    response.status_code = status_code
    return response


def test_post_with_retry_succeeds_immediately():
    with patch("app.publishers.http_utils.httpx.post", return_value=_mock_response(200)):
        assert http_utils.post_with_retry("https://x.test/secret-token", {}, 15, "test:ok") is True


def test_post_with_retry_retries_on_429_then_succeeds():
    responses = [_mock_response(429), _mock_response(200)]
    with patch("app.publishers.http_utils.httpx.post", side_effect=responses), \
         patch("app.publishers.http_utils.time.sleep"):
        assert http_utils.post_with_retry("https://x.test/secret-token", {}, 15, "test:retry") is True


def test_post_with_retry_gives_up_after_max_attempts_without_raising():
    with patch("app.publishers.http_utils.httpx.post", return_value=_mock_response(500)), \
         patch("app.publishers.http_utils.time.sleep"):
        result = http_utils.post_with_retry("https://x.test/secret-token", {}, 15, "test:fail")
    assert result is False


def test_post_with_retry_handles_timeout_without_raising():
    with patch("app.publishers.http_utils.httpx.post", side_effect=httpx.TimeoutException("x")), \
         patch("app.publishers.http_utils.time.sleep"):
        result = http_utils.post_with_retry("https://x.test/secret-token", {}, 15, "test:timeout")
    assert result is False


def test_no_secret_url_leaked_in_logs_on_http_error(caplog):
    """
    Garantie de sécurité centrale : même si httpx lève une exception dont la
    représentation texte contient l'URL (donc un token), cette URL ne doit
    JAMAIS apparaître dans un message de log.
    """
    secret_token = "SUPER-SECRET-TOKEN-123"
    url_with_secret = f"https://api.telegram.org/bot{secret_token}/sendMessage"

    class FakeHTTPError(httpx.HTTPError):
        def __str__(self):
            return f"Error calling {url_with_secret}"

    with caplog.at_level(logging.ERROR), \
         patch("app.publishers.http_utils.httpx.post", side_effect=FakeHTTPError("boom")):
        http_utils.post_with_retry(url_with_secret, {}, 15, "telegram:test")

    for record in caplog.records:
        assert secret_token not in record.getMessage()


def test_discord_publish_returns_false_when_no_webhook_configured(monkeypatch):
    monkeypatch.setattr(discord_publisher.settings, "discord_webhook_urgent", "")
    monkeypatch.setattr(discord_publisher.settings, "discord_webhook_digest", "")
    assert discord_publisher.publish({"embeds": []}, mode="urgent") is False


def test_telegram_publish_returns_false_when_not_configured(monkeypatch):
    monkeypatch.setattr(telegram_publisher.settings, "telegram_bot_token", "")
    assert telegram_publisher.publish_to_channel("test") is False


def test_discord_webhook_has_priority_over_bot(monkeypatch):
    monkeypatch.setattr(discord_publisher.settings, "discord_webhook_urgent", "https://discord.test/webhook")
    with patch.object(discord_publisher, "post_with_retry", return_value=True) as webhook, \
         patch.object(discord_bot, "publish") as bot:
        assert discord_publisher.publish({"embeds": []}, mode="urgent") is True
    webhook.assert_called_once()
    bot.assert_not_called()


def test_discord_bot_is_used_when_webhook_is_absent(monkeypatch):
    monkeypatch.setattr(discord_publisher.settings, "discord_webhook_digest", "")
    monkeypatch.setattr(discord_publisher.settings, "discord_token", "bot-token")
    monkeypatch.setattr(discord_publisher.settings, "discord_channel_digest_id", "123456")
    with patch.object(discord_bot, "publish", return_value=True) as bot:
        assert discord_publisher.publish({"embeds": []}, mode="digest") is True
    bot.assert_called_once_with({"embeds": []}, mode="digest")


def test_discord_bot_channel_overrides_default(monkeypatch):
    monkeypatch.setattr(discord_bot.settings, "discord_token", "bot-token")
    monkeypatch.setattr(discord_bot.settings, "discord_channel_id", "100")
    monkeypatch.setattr(discord_bot.settings, "discord_channel_urgent_id", "200")
    assert discord_bot._channel_id("urgent") == 200
    assert discord_bot._channel_id("digest") == 100
