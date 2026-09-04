"""Client Discord classique exécuté dans une boucle asyncio dédiée.

Le pipeline et APScheduler restent synchrones : publish() soumet une coroutine
à cette boucle et attend son résultat avec un timeout borné.
"""
import asyncio
import logging
import threading
from typing import Optional

import discord

from app.config import settings

logger = logging.getLogger("segenghost.discord_bot")

_client: Optional[discord.Client] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_thread: Optional[threading.Thread] = None
_start_lock = threading.Lock()


class _DiscordClient(discord.Client):
    async def on_ready(self):
        logger.info("Bot Discord connecté.")


def is_configured() -> bool:
    return bool(settings.discord_token and (
        settings.discord_channel_id
        or settings.discord_channel_urgent_id
        or settings.discord_channel_digest_id
    ))


def _channel_id(mode: str) -> Optional[int]:
    raw_id = (
        settings.discord_channel_urgent_id if mode == "urgent"
        else settings.discord_channel_digest_id
    ) or settings.discord_channel_id
    if not raw_id:
        return None
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        logger.error("Identifiant de salon Discord invalide pour le mode '%s'.", mode)
        return None


def _run_client() -> None:
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    try:
        _loop.run_until_complete(_client.start(settings.discord_token))
    except Exception as exc:
        logger.error("Connexion du bot Discord échouée (%s).", type(exc).__name__)
    finally:
        _loop.close()
        _loop = None


def start() -> bool:
    """Démarre le bot une seule fois dans un thread daemon non bloquant."""
    global _client, _thread
    if not settings.discord_token:
        return False
    with _start_lock:
        if _thread and _thread.is_alive():
            return True
        intents = discord.Intents.none()
        intents.guilds = True
        _client = _DiscordClient(intents=intents)
        _thread = threading.Thread(target=_run_client, name="discord-bot", daemon=True)
        _thread.start()
    return True


async def _send_payload(payload: dict, mode: str) -> bool:
    if _client is None:
        return False
    await _client.wait_until_ready()
    channel_id = _channel_id(mode)
    if channel_id is None:
        return False
    channel = _client.get_channel(channel_id)
    if channel is None:
        try:
            channel = await _client.fetch_channel(channel_id)
        except Exception as exc:
            logger.error("Salon Discord inaccessible [%s] (%s).", mode, type(exc).__name__)
            return False
    embeds = [discord.Embed.from_dict(embed) for embed in payload.get("embeds", [])]
    if not embeds:
        logger.error("Payload Discord sans embed [%s].", mode)
        return False
    await channel.send(embeds=embeds)
    return True


def publish(payload: dict, mode: str) -> bool:
    """Publie un embed via le bot classique, sans bloquer le thread appelant."""
    loop = _loop
    if loop is None or _client is None or not _thread or not _thread.is_alive():
        logger.warning("Bot Discord non connecté [%s].", mode)
        return False
    future = asyncio.run_coroutine_threadsafe(_send_payload(payload, mode), loop)
    try:
        return bool(future.result(timeout=settings.http_timeout_seconds))
    except (TimeoutError, asyncio.TimeoutError):
        future.cancel()
        logger.error("Publication Discord par bot dépassée [%s].", mode)
        return False
    except Exception as exc:
        logger.error("Publication Discord par bot échouée [%s] (%s).", mode, type(exc).__name__)
        return False


async def _close_client() -> None:
    if _client and not _client.is_closed():
        await _client.close()


def stop() -> None:
    """Arrête proprement le client sans attendre indéfiniment le thread."""
    loop = _loop
    if loop and _client:
        future = asyncio.run_coroutine_threadsafe(_close_client(), loop)
        try:
            future.result(timeout=settings.http_timeout_seconds)
        except Exception as exc:
            logger.warning("Arrêt du bot Discord incomplet (%s).", type(exc).__name__)
