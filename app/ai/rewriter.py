"""
Rédaction contrôlée via l'API Anthropic.

Principe : l'IA reçoit UNIQUEMENT des données structurées et vérifiées.
Après génération, ce module vérifie que les identifiants factuels
(CVE, score CVSS) présents dans les données d'entrée n'ont pas été altérés
dans le texte généré. En cas d'anomalie, la publication est bloquée.

Résilience : toute erreur d'appel API (timeout, indisponibilité, erreur
d'authentification, réponse vide) est interceptée ici et se traduit par un
retour None — jamais par une exception qui remonterait au pipeline. Un échec
de rédaction pour UN article ne doit jamais interrompre le traitement des
autres.
"""
import logging
import time
from typing import Dict, Optional

import anthropic

from app.config import settings
from app.ai.prompts import SYSTEM_PROMPT_URGENT, SYSTEM_PROMPT_DIGEST_ITEM

logger = logging.getLogger("segenghost.ai")

_client: Optional[anthropic.Anthropic] = None

# Erreurs considérées comme transitoires : on retente avant d'abandonner.
_RETRYABLE_EXCEPTIONS = (
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


def _get_client() -> Optional[anthropic.Anthropic]:
    global _client
    if not settings.anthropic_api_key:
        logger.error("ANTHROPIC_API_KEY manquant — rédaction IA indisponible pour cet appel.")
        return None
    if _client is None:
        _client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.ai_timeout_seconds,
        )
    return _client


def _build_structured_input(article: Dict) -> str:
    """Construit le bloc de données structurées transmis à l'IA (jamais une instruction ouverte)."""
    return (
        f"Titre: {article.get('title', 'non disponible')}\n"
        f"Source: {article.get('source', 'non disponible')}\n"
        f"URL source: {article.get('source_url', 'non disponible')}\n"
        f"CVE: {article.get('cve_id') or 'non disponible'}\n"
        f"Score CVSS: {article.get('cvss_score') if article.get('cvss_score') is not None else 'non disponible'}\n"
        f"Exploitation confirmée: {'Oui' if article.get('exploited') else 'non disponible'}\n"
        f"Catégorie: {article.get('category', 'non disponible')}\n"
        f"Zone géographique ciblée: {article.get('region') or 'non disponible'}\n"
        f"Résumé brut de la source: {article.get('raw_summary', 'non disponible')}\n"
    )


def _validate_factual_integrity(article: Dict, generated_text: str) -> bool:
    """
    Contrôle basique post-génération : si un CVE ou un score CVSS était présent
    dans les données d'entrée, il doit apparaître tel quel dans le texte généré.
    """
    if not generated_text:
        logger.warning("Validation échouée : réponse IA vide.")
        return False

    cve_id = article.get("cve_id")
    if cve_id and cve_id not in generated_text:
        logger.warning("Validation échouée : CVE %s absent du texte généré", cve_id)
        return False

    cvss_score = article.get("cvss_score")
    if cvss_score is not None:
        if str(cvss_score) not in generated_text:
            logger.warning("Validation échouée : score CVSS %s absent du texte généré", cvss_score)
            return False

    return True


def _call_ai(system_prompt: str, structured_input: str, max_tokens: int, label: str) -> Optional[str]:
    """
    Appelle l'API avec retry/backoff sur erreurs transitoires.
    Retourne le texte généré, ou None si l'appel échoue définitivement —
    ce cas doit être traité par l'appelant comme "rien à publier", pas comme
    une erreur fatale.
    """
    client = _get_client()
    if client is None:
        return None

    last_exception_type = None

    for attempt in range(1, settings.ai_max_retries + 2):
        try:
            response = client.messages.create(
                model=settings.ai_model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": structured_input}],
            )
            return "".join(
                block.text for block in response.content if block.type == "text"
            ).strip()

        except _RETRYABLE_EXCEPTIONS as exc:
            last_exception_type = type(exc).__name__
            if attempt <= settings.ai_max_retries:
                wait = 1.5 * (2 ** (attempt - 1))
                logger.warning(
                    "Rédaction IA [%s] : %s (tentative %d/%d), nouvelle tentative dans %.1fs",
                    label, last_exception_type, attempt, settings.ai_max_retries + 1, wait,
                )
                time.sleep(wait)
                continue

        except anthropic.APIStatusError as exc:
            # Erreur non transitoire (ex. 400, 401, 403) — inutile de réessayer.
            logger.error("Rédaction IA [%s] échouée : erreur API (statut %s)", label, exc.status_code)
            return None

        except Exception as exc:
            # Filet de sécurité : toute erreur imprévue ne doit jamais remonter
            # jusqu'au pipeline. On journalise le type d'erreur uniquement
            # (jamais la clé API, jamais le contenu brut de la requête).
            logger.error("Rédaction IA [%s] échouée : erreur inattendue (%s)", label, type(exc).__name__)
            return None

    logger.error(
        "Rédaction IA [%s] échouée définitivement après %d tentative(s) (%s)",
        label, settings.ai_max_retries + 1, last_exception_type,
    )
    return None


def rewrite_urgent(article: Dict) -> Optional[str]:
    """Génère le texte d'une alerte urgente. Retourne None si l'appel ou la validation échoue."""
    structured_input = _build_structured_input(article)
    generated_text = _call_ai(SYSTEM_PROMPT_URGENT, structured_input, max_tokens=500, label="urgent")

    if generated_text is None:
        return None
    if not _validate_factual_integrity(article, generated_text):
        return None

    return generated_text


def rewrite_digest_item(article: Dict) -> Optional[str]:
    """Génère le résumé court d'un item de digest. Retourne None si l'appel ou la validation échoue."""
    structured_input = _build_structured_input(article)
    generated_text = _call_ai(SYSTEM_PROMPT_DIGEST_ITEM, structured_input, max_tokens=250, label="digest")

    if generated_text is None:
        return None
    if not _validate_factual_integrity(article, generated_text):
        return None

    return generated_text
