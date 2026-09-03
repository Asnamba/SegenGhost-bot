"""
Publication sur Discord via Webhooks (aucun risque de suspension — canal officiel).

Sécurité : l'URL du webhook contient un secret (ID + token) dans son chemin.
Elle n'est jamais transmise au logger — voir http_utils.post_with_retry.
"""
import logging

from app.config import settings
from app.publishers.http_utils import post_with_retry

logger = logging.getLogger("segenghost.discord")


def publish(payload: dict, mode: str = "digest") -> bool:
    """Envoie un payload (embed) vers le webhook Discord correspondant au mode."""
    webhook_url = (
        settings.discord_webhook_urgent if mode == "urgent" else settings.discord_webhook_digest
    )
    if not webhook_url:
        logger.warning("Aucun webhook Discord configuré pour le mode '%s' — publication ignorée.", mode)
        return False

    return post_with_retry(
        url=webhook_url,
        json_payload=payload,
        timeout=settings.http_timeout_seconds,
        safe_label=f"discord:{mode}",
    )
