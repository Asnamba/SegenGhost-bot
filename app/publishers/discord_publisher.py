"""
Publication sur Discord via Webhooks (aucun risque de suspension — canal officiel).

Sécurité : l'URL du webhook contient un secret (ID + token) dans son chemin.
Elle n'est jamais transmise au logger — voir http_utils.post_with_retry.
"""
import logging

from app.config import settings
from app.publishers import discord_bot
from app.publishers.http_utils import post_with_retry

logger = logging.getLogger("segenghost.discord")


def publish(payload: dict, mode: str = "digest") -> bool:
    """Envoie par webhook si configuré, sinon par bot Discord classique."""
    webhook_url = (
        settings.discord_webhook_urgent if mode == "urgent" else settings.discord_webhook_digest
    )
    if webhook_url:
        return post_with_retry(
            url=webhook_url,
            json_payload=payload,
            timeout=settings.http_timeout_seconds,
            safe_label=f"discord:{mode}",
        )

    if discord_bot.is_configured():
        return discord_bot.publish(payload, mode=mode)

    logger.warning("Aucun webhook ou bot Discord configuré pour '%s'.", mode)
    return False
