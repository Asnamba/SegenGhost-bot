"""
Utilitaire HTTP partagé pour les publishers (Discord, Telegram).

Deux préoccupations centrales :
1. Résilience : les publications échouent parfois pour des raisons transitoires
   (timeout, erreur réseau, 429 rate limit, 5xx serveur) — on retente avec un
   backoff exponentiel court avant d'abandonner, sans jamais faire planter le pipeline.
2. Sécurité des logs : les URLs de webhook Discord et d'API Telegram contiennent
   un secret dans leur chemin (token du bot / token du webhook). On ne logue
   JAMAIS l'URL brute ni la représentation par défaut d'une exception httpx
   (qui inclut l'URL de la requête) — uniquement un identifiant safe fourni
   par l'appelant et le code de statut HTTP le cas échéant.
"""
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger("segenghost.http")

MAX_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 1.5
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def post_with_retry(url: str, json_payload: dict, timeout: float, safe_label: str) -> bool:
    """
    Envoie une requête POST JSON avec retry/backoff sur erreurs transitoires.

    - url / json_payload / timeout : paramètres de la requête (jamais loggués tels quels).
    - safe_label : identifiant sans secret utilisé dans les logs (ex: "discord:urgent",
      "telegram:admin").

    Retourne True si la requête a fini par aboutir (statut 2xx), False sinon.
    """
    last_status: Optional[int] = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = httpx.post(url, json=json_payload, timeout=timeout)
            last_status = response.status_code

            if response.status_code < 300:
                return True

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_ATTEMPTS:
                wait = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "Publication [%s] : statut %s (tentative %d/%d), nouvelle tentative dans %.1fs",
                    safe_label, response.status_code, attempt, MAX_ATTEMPTS, wait,
                )
                time.sleep(wait)
                continue

            logger.error(
                "Publication [%s] échouée définitivement : statut HTTP %s",
                safe_label, response.status_code,
            )
            return False

        except httpx.TimeoutException:
            if attempt < MAX_ATTEMPTS:
                wait = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "Publication [%s] : timeout (tentative %d/%d), nouvelle tentative dans %.1fs",
                    safe_label, attempt, MAX_ATTEMPTS, wait,
                )
                time.sleep(wait)
                continue
            logger.error("Publication [%s] échouée : timeout après %d tentatives", safe_label, MAX_ATTEMPTS)
            return False

        except httpx.HTTPError:
            # Ne jamais logger l'exception elle-même : sa représentation texte
            # inclut l'URL de la requête, qui contient un secret (token).
            logger.error(
                "Publication [%s] échouée : erreur réseau/HTTP (dernier statut connu : %s)",
                safe_label, last_status,
            )
            return False

    return False
