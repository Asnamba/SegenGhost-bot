"""
Configuration centrale de SegenGhost Security.
Toutes les valeurs sensibles (tokens, clés API) sont lues depuis les variables
d'environnement — jamais codées en dur ici, et jamais logguées.
"""
import logging
import os
from secrets import compare_digest
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("segenghost.config")


@dataclass
class Settings:
    # --- Base de données ---
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./segenghost.db")

    # --- Discord ---
    discord_webhook_urgent: str = os.getenv("DISCORD_WEBHOOK_URGENT", "")
    discord_webhook_digest: str = os.getenv("DISCORD_WEBHOOK_DIGEST", "")
    discord_token: str = os.getenv("DISCORD_TOKEN", "")
    discord_channel_id: str = os.getenv("DISCORD_CHANNEL_ID", "")
    discord_channel_urgent_id: str = os.getenv("DISCORD_CHANNEL_URGENT_ID", "")
    discord_channel_digest_id: str = os.getenv("DISCORD_CHANNEL_DIGEST_ID", "")

    # --- Telegram ---
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_admin_chat_id: str = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
    telegram_channel_chat_id: str = os.getenv("TELEGRAM_CHANNEL_CHAT_ID", "")

    # --- IA (rédaction contrôlée) ---
    ai_provider: str = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    mistral_api_key: str = os.getenv("MISTRAL_API_KEY", "")
    ai_provider_priority: str = os.getenv(
        "AI_PROVIDER_PRIORITY", "groq,gemini,mistral"
    )
    ai_model: str = os.getenv("AI_MODEL", "claude-sonnet-4-6")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
    ai_max_retries: int = int(os.getenv("AI_MAX_RETRIES", "2"))
    ai_timeout_seconds: float = float(os.getenv("AI_TIMEOUT_SECONDS", "30"))

    # --- Seuils de classification ---
    cvss_urgent_threshold: float = float(os.getenv("CVSS_URGENT_THRESHOLD", "8.5"))

    # --- Planification du digest (heures locales, format HH:MM) ---
    digest_times: List[str] = field(default_factory=lambda: ["08:00", "14:00", "19:00"])

    # --- Fréquence de collecte (minutes) ---
    collect_interval_minutes: int = int(os.getenv("COLLECT_INTERVAL_MINUTES", "60"))

    # --- Réseau / résilience ---
    http_timeout_seconds: float = float(os.getenv("HTTP_TIMEOUT_SECONDS", "15"))
    rss_fetch_max_retries: int = int(os.getenv("RSS_FETCH_MAX_RETRIES", "2"))
    rejected_retention_days: int = int(os.getenv("REJECTED_RETENTION_DAYS", "30"))
    published_retention_days: int = int(os.getenv("PUBLISHED_RETENTION_DAYS", "90"))

    # --- Logging ---
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # --- Protection des routes d'administration et du dashboard ---
    admin_api_token: str = os.getenv("ADMIN_API_TOKEN", "")
    dashboard_username: str = os.getenv("DASHBOARD_USERNAME", "")
    dashboard_password: str = os.getenv("DASHBOARD_PASSWORD", "")
    scheduler_enabled: bool = os.getenv("SCHEDULER_ENABLED", "true").lower() in {"1", "true", "yes"}


settings = Settings()


def validate_config() -> List[str]:
    """
    Vérifie la présence des variables jugées nécessaires au fonctionnement complet.
    Ne lève pas d'exception : le bot doit pouvoir démarrer en mode dégradé
    (ex. dashboard consultable même si Discord/Telegram ne sont pas configurés),
    mais chaque absence est clairement signalée au démarrage.
    Retourne la liste des avertissements (chaîne vide si tout est configuré).
    """
    warnings: List[str] = []

    supported_providers = {"groq", "gemini", "mistral", "anthropic"}
    if settings.ai_provider not in supported_providers:
        warnings.append("AI_PROVIDER invalide — utiliser groq, gemini, mistral ou anthropic.")
    configured_keys = {
        "groq": settings.groq_api_key,
        "gemini": settings.gemini_api_key,
        "mistral": settings.mistral_api_key,
        "anthropic": settings.anthropic_api_key,
    }
    priority_providers = [
        provider.strip().lower()
        for provider in settings.ai_provider_priority.split(",")
        if provider.strip().lower() in supported_providers
    ]
    usable_provider = any(configured_keys.get(provider) for provider in priority_providers)
    if not configured_keys.get(settings.ai_provider) and not usable_provider:
        warnings.append(
            "Aucune clé API IA configurée pour les fournisseurs prioritaires."
        )

    if not settings.admin_api_token:
        warnings.append("ADMIN_API_TOKEN manquant — les endpoints de déclenchement restent désactivés.")
    if not settings.dashboard_username or not settings.dashboard_password:
        warnings.append("DASHBOARD_USERNAME/PASSWORD manquants — le dashboard reste accessible sans authentification.")

    webhook_configured = settings.discord_webhook_urgent or settings.discord_webhook_digest
    bot_configured = settings.discord_token and (
        settings.discord_channel_id
        or settings.discord_channel_urgent_id
        or settings.discord_channel_digest_id
    )
    if not webhook_configured and not bot_configured:
        warnings.append("Aucun webhook ou bot Discord configuré — publication Discord désactivée.")

    if not settings.telegram_bot_token:
        warnings.append("TELEGRAM_BOT_TOKEN manquant — publication Telegram désactivée.")
    else:
        if not settings.telegram_channel_chat_id:
            warnings.append("TELEGRAM_CHANNEL_CHAT_ID manquant — publication sur le canal désactivée.")
        if not settings.telegram_admin_chat_id:
            warnings.append("TELEGRAM_ADMIN_CHAT_ID manquant — notification admin (relai WhatsApp) désactivée.")

    for warning in warnings:
        logger.warning("Configuration incomplète : %s", warning)

    if not warnings:
        logger.info("Configuration validée : toutes les variables attendues sont présentes.")

    return warnings
