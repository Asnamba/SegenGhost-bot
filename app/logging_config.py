"""
Configuration centralisée du logging.

Principe : chaque module logue via son propre logger nommé "segenghost.<module>",
ce qui permet de filtrer/rediriger facilement (fichier, stdout, service externe)
sans toucher au code métier. Aucun secret (token, clé API) ne doit jamais
transiter dans un message de log — voir en particulier
app/publishers/http_utils.py pour la justification sur les URLs de webhook.
"""
import logging

from app.config import settings


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # Les bibliothèques tierces sont souvent bruyantes en DEBUG/INFO — on les
    # limite au niveau WARNING pour garder des logs lisibles.
    for noisy_logger in ("httpx", "httpcore", "apscheduler"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    logging.getLogger("segenghost.startup").info(
        "Logging configuré au niveau %s.", settings.log_level.upper()
    )
