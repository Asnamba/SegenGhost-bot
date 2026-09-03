"""
Publication sur Telegram via l'API officielle Bot (aucun risque de suspension).
Deux destinations possibles :
- le canal public SegenGhost Security (abonnés)
- le chat privé de l'administrateur (notification push immédiate + texte
  prêt à relayer manuellement sur la chaîne WhatsApp)

Sécurité : l'URL de l'API Telegram contient le token du bot dans son chemin.
Elle n'est jamais transmise au logger — voir http_utils.post_with_retry.
"""
import logging

from app.config import settings
from app.publishers.http_utils import post_with_retry

logger = logging.getLogger("segenghost.telegram")

API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def _send(chat_id: str, text: str, safe_label: str) -> bool:
    if not settings.telegram_bot_token or not chat_id:
        logger.warning("Configuration Telegram incomplète [%s] — publication ignorée.", safe_label)
        return False

    url = API_BASE.format(token=settings.telegram_bot_token)
    return post_with_retry(
        url=url,
        json_payload={"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
        timeout=settings.http_timeout_seconds,
        safe_label=safe_label,
    )


def publish_to_channel(text: str) -> bool:
    """Publie sur le canal Telegram public (abonnés SegenGhost Security)."""
    return _send(settings.telegram_channel_chat_id, text, safe_label="telegram:channel")


def notify_admin(text: str, whatsapp_ready_text: str) -> bool:
    """
    Notifie l'administrateur en privé (notification push immédiate) et lui
    fournit le texte prêt à copier/coller sur la chaîne WhatsApp.
    """
    message = (
        f"{text}\n\n"
        f"— — — — — — — — — —\n"
        f"📋 Texte prêt pour la chaîne WhatsApp :\n\n"
        f"{whatsapp_ready_text}"
    )
    return _send(settings.telegram_admin_chat_id, message, safe_label="telegram:admin")
