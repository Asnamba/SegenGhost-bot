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
    """Envoie par bot si configuré, sinon par webhook Discord."""
    if discord_bot.is_configured(mode=mode):
        logger.info("Publication Discord [%s] : mode bot actif, envoi via channel.send().", mode)
        return discord_bot.publish(payload, mode=mode)

    if settings.discord_token and not (
        settings.discord_channel_id
        or settings.discord_channel_urgent_id
        or settings.discord_channel_digest_id
    ):
        logger.info(
            "Publication Discord [%s] : DISCORD_CHANNEL_ID non configuré, fallback webhook recherché.",
            mode,
        )

    webhook_url = (
        settings.discord_webhook_urgent if mode == "urgent" else settings.discord_webhook_digest
    )
    if webhook_url:
        logger.info("Publication Discord [%s] : mode webhook actif.", mode)
        return post_with_retry(
            url=webhook_url,
            json_payload=payload,
            timeout=settings.http_timeout_seconds,
            safe_label=f"discord:{mode}",
        )

    logger.warning(
        "Publication Discord [%s] désactivée : aucun webhook et aucun bot Discord configuré.",
        mode,
    )
    return False
