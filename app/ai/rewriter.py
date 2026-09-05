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
import asyncio
from difflib import SequenceMatcher
import logging
import time
from typing import Dict, Optional

import anthropic
import httpx
from google import genai
from google.genai import types

from app.config import settings
from app.database import AIUsage, get_session
from app.ai.prompts import SYSTEM_PROMPT_URGENT, SYSTEM_PROMPT_DIGEST_ITEM

logger = logging.getLogger("segenghost.ai")

_client: Optional[anthropic.Anthropic] = None
_gemini_client: Optional[genai.Client] = None

PROVIDER_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "mistral": "mistral-small-latest",
}
PROVIDER_KEYS = {
    "groq": "groq_api_key",
    "gemini": "gemini_api_key",
    "mistral": "mistral_api_key",
    "anthropic": "anthropic_api_key",
}
STRICT_PROVIDER_ORDER = ("gemini", "groq", "mistral", "anthropic")


def _record_usage(provider: str, article: Dict, success: bool, error_message: str | None = None):
    article_id = article.get("id")
    if article_id is None:
        return
    session = None
    try:
        session = get_session()
        session.add(AIUsage(
            provider=provider,
            success=success,
            article_id=article_id,
            error_message=error_message[:255] if error_message else None,
        ))
        session.commit()
    except Exception as exc:
        if session is not None:
            session.rollback()
        logger.warning("Enregistrement usage IA impossible (%s).", type(exc).__name__)
    finally:
        if session is not None:
            session.close()

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


def _get_gemini_client() -> Optional[genai.Client]:
    global _gemini_client
    if not settings.gemini_api_key:
        logger.error("GEMINI_API_KEY manquant — rédaction IA indisponible pour cet appel.")
        return None
    if _gemini_client is None:
        _gemini_client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=int(settings.ai_timeout_seconds * 1000)),
        )
    return _gemini_client


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
    if not isinstance(generated_text, str) or not generated_text.strip():
        logger.warning("Validation échouée : réponse IA vide.")
        return False

    source_text = (article.get("raw_summary") or "").strip()
    if source_text and SequenceMatcher(None, source_text.lower(), generated_text.strip().lower()).ratio() >= 0.90:
        logger.warning("Validation échouée : texte généré quasi identique au résumé source.")
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


def _call_anthropic(system_prompt: str, structured_input: str, max_tokens: int, label: str) -> Optional[str]:
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


async def _call_openai_compatible(
    provider: str,
    api_key: str,
    system_prompt: str,
    structured_input: str,
    max_tokens: int,
    label: str,
    article: Dict,
) -> Optional[str]:
    endpoints = {
        "groq": "https://api.groq.com/openai/v1/chat/completions",
        "mistral": "https://api.mistral.ai/v1/chat/completions",
    }
    payload = {
        "model": PROVIDER_MODELS[provider],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": structured_input},
        ],
        "max_tokens": max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
            response = await client.post(
                endpoints[provider],
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            if response.status_code in {408, 429, 500, 502, 503, 504}:
                _record_usage(provider, article, False, f"HTTP {response.status_code}")
                logger.warning("Rédaction IA [%s] indisponible (%s).", label, response.status_code)
                return None
            response.raise_for_status()
            data = response.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content")
            result = text.strip() if isinstance(text, str) and text.strip() else None
            _record_usage(provider, article, result is not None, "réponse vide" if result is None else None)
            return result
    except Exception as exc:
        _record_usage(provider, article, False, type(exc).__name__)
        logger.warning("Rédaction IA [%s] échouée (%s).", label, type(exc).__name__)
        return None


async def _call_provider_async(
    provider: str, system_prompt: str, structured_input: str, max_tokens: int, label: str, article: Dict
) -> Optional[str]:
    api_key = getattr(settings, PROVIDER_KEYS[provider], "")
    if not api_key:
        logger.info("Fournisseur IA [%s] ignoré : clé API absente.", provider)
        return None
    if provider in {"groq", "mistral"}:
        return await _call_openai_compatible(
            provider, api_key, system_prompt, structured_input, max_tokens, label, article
        )
    # Les SDK Gemini/Anthropic restent synchrones ici, isolés dans un thread.
    call = _call_gemini if provider == "gemini" else _call_anthropic
    result = await asyncio.to_thread(call, system_prompt, structured_input, max_tokens, label)
    _record_usage(provider, article, result is not None, "échec SDK" if result is None else None)
    return result


async def rewrite_article_async(article: Dict, urgent: bool = False) -> Optional[str]:
    """Réécrit un article selon la cascade stricte, sans publier de texte brut."""
    system_prompt = SYSTEM_PROMPT_URGENT if urgent else SYSTEM_PROMPT_DIGEST_ITEM
    max_tokens = 500 if urgent else 250
    structured_input = _build_structured_input(article)
    for provider in STRICT_PROVIDER_ORDER:
        try:
            generated_text = await _call_provider_async(
                provider, system_prompt, structured_input, max_tokens,
                "urgent" if urgent else "digest", article,
            )
        except Exception as exc:
            generated_text = None
            logger.warning("Provider IA %s échoué (%s), fallback suivant.", provider, type(exc).__name__)

        try:
            valid = bool(generated_text and _validate_factual_integrity(article, generated_text))
        except Exception as exc:
            valid = False
            logger.warning("Validation IA %s échouée (%s), fallback suivant.", provider, type(exc).__name__)
        if valid:
            logger.info("Article réécrit avec succès par %s.", provider)
            return generated_text
        logger.warning("Provider IA %s indisponible ou réponse invalide, fallback suivant.", provider)

    logger.error(
        "Aucun provider IA n'a produit une rédaction valide pour l'article %s; publication bloquée.",
        article.get("title", "inconnu"),
    )
    return None


async def process_article_with_fallback(article: Dict, urgent: bool = False) -> str:
    """API publique de traitement IA : elle retourne toujours un texte publiable."""
    return await rewrite_article_async(article, urgent=urgent)


def _is_gemini_retryable(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {408, 429, 500, 502, 503, 504}:
        return True
    return any(name in type(exc).__name__.lower() for name in ("timeout", "connection", "ratelimit", "server"))


def _call_gemini(system_prompt: str, structured_input: str, max_tokens: int, label: str) -> Optional[str]:
    """Appelle Gemini avec le même contrat de résilience que le chemin Anthropic."""
    client = _get_gemini_client()
    if client is None:
        return None

    last_exception_type = None
    for attempt in range(1, settings.ai_max_retries + 2):
        try:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=structured_input,
                config=types.GenerateContentConfig(
                    systemInstruction=system_prompt,
                    maxOutputTokens=max_tokens,
                ),
            )
            generated_text = getattr(response, "text", None)
            return generated_text.strip() if generated_text else None
        except Exception as exc:
            last_exception_type = type(exc).__name__
            if _is_gemini_retryable(exc) and attempt <= settings.ai_max_retries:
                wait = 1.5 * (2 ** (attempt - 1))
                logger.warning(
                    "Rédaction IA Gemini [%s] : %s (tentative %d/%d), nouvelle tentative dans %.1fs",
                    label, last_exception_type, attempt, settings.ai_max_retries + 1, wait,
                )
                time.sleep(wait)
                continue
            logger.error("Rédaction IA Gemini [%s] échouée : erreur (%s)", label, last_exception_type)
            return None

    logger.error(
        "Rédaction IA Gemini [%s] échouée définitivement après %d tentative(s) (%s)",
        label, settings.ai_max_retries + 1, last_exception_type,
    )
    return None


def rewrite_urgent(article: Dict) -> str:
    """Génère le texte d'une alerte urgente, avec fallback local garanti."""
    return asyncio.run(rewrite_article_async(article, urgent=True))


def rewrite_digest_item(article: Dict) -> str:
    """Génère le résumé court d'un item de digest, avec fallback local garanti."""
    return asyncio.run(rewrite_article_async(article, urgent=False))
