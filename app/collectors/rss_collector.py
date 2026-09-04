"""
Collecteur RSS.
Interroge chaque source définie dans sources.py et retourne une liste
d'entrées brutes normalisées, prêtes pour le pipeline de traitement.
Aucune reformulation ici : on ne fait que récupérer le texte source tel quel.

Robustesse : chaque source est isolée — une source indisponible, lente ou
malformée n'empêche jamais la collecte des autres. Le fetch réseau passe par
httpx (timeout explicite + retry court avec backoff) plutôt que de laisser
feedparser ouvrir la connexion lui-même, car ce dernier ne garantit pas de
timeout et peut bloquer indéfiniment sur une source qui ne répond pas.
"""
import hashlib
import ipaddress
import logging
import time
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import urlparse

import feedparser
import httpx

from app.collectors.sources import SOURCES
from app.config import settings

logger = logging.getLogger("segenghost.collector")

ALLOWED_SCHEMES = {"http", "https"}


def _hash_entry(source_name: str, link: str, title: str) -> str:
    raw = f"{source_name}|{link}|{title}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _is_safe_url(url: str) -> bool:
    """N'autorise que des URLs web publiques et sans identifiant intégré."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ALLOWED_SCHEMES or not parsed.hostname or parsed.username or parsed.password:
            return False
        try:
            address = ipaddress.ip_address(parsed.hostname)
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
                return False
        except ValueError:
            pass
        return True
    except ValueError:
        return False


def _fetch_feed_bytes(name: str, url: str) -> Optional[bytes]:
    """
    Récupère le contenu brut d'un flux avec timeout explicite et retry court.
    Retourne None si la source reste inaccessible après les tentatives prévues
    — l'appelant doit alors simplement ignorer cette source pour ce cycle.
    """
    last_error: Optional[str] = None

    for attempt in range(1, settings.rss_fetch_max_retries + 2):
        try:
            response = httpx.get(
                url,
                timeout=settings.http_timeout_seconds,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                },
            )
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > 5_000_000:
                logger.error("Source '%s' ignorée : flux trop volumineux", name)
                return None
            response.raise_for_status()
            final_url = getattr(response, "url", None)
            if isinstance(final_url, (str, httpx.URL)) and not _is_safe_url(str(final_url)):
                logger.error("Source '%s' ignorée : redirection vers une URL non sûre", name)
                return None
            if len(response.content) > 5_000_000:
                logger.error("Source '%s' ignorée : flux trop volumineux", name)
                return None
            return response.content
        except httpx.TimeoutException:
            last_error = "timeout"
        except httpx.HTTPStatusError as exc:
            last_error = f"statut HTTP {exc.response.status_code}"
        except httpx.HTTPError as exc:
            last_error = f"erreur réseau ({type(exc).__name__})"

        if attempt <= settings.rss_fetch_max_retries:
            wait = 1.5 * (2 ** (attempt - 1))
            logger.warning(
                "Source '%s' : %s (tentative %d/%d), nouvelle tentative dans %.1fs",
                name, last_error, attempt, settings.rss_fetch_max_retries + 1, wait,
            )
            time.sleep(wait)

    logger.error(
        "Source '%s' ignorée pour ce cycle : injoignable après %d tentative(s) (%s)",
        name, settings.rss_fetch_max_retries + 1, last_error,
    )
    return None


def _collect_source(source: Dict) -> List[Dict]:
    """Collecte les entrées d'UNE source. Isolé pour qu'une erreur ne se propage jamais aux autres."""
    name, url = source["name"], source["url"]

    if not _is_safe_url(url):
        logger.error("Source '%s' ignorée : URL invalide ou schéma non autorisé (%s)", name, url)
        return []

    raw_bytes = _fetch_feed_bytes(name, url)
    if raw_bytes is None:
        return []

    try:
        feed = feedparser.parse(raw_bytes)
    except Exception as exc:
        logger.error("Source '%s' ignorée : flux illisible (%s)", name, type(exc).__name__)
        return []

    if feed.bozo and not feed.entries:
        logger.warning("Flux vide ou malformé pour '%s'", name)
        return []

    entries = []
    for entry in feed.entries:
        try:
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "").strip()
            summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
            published = getattr(entry, "published", None)
            image_url = _extract_image_url(entry)

            if not title or not link:
                continue
            if not _is_safe_url(link):
                logger.warning("Entrée ignorée dans '%s' : lien non sûr", name)
                continue

            entries.append({
                "source": name,
                "source_url": link,
                "image_url": image_url,
                "title": title,
                "raw_summary": summary,
                "content_hash": _hash_entry(name, link, title),
                "published_raw": published,
                "collected_at": datetime.utcnow(),
            })
        except Exception as exc:
            # Un item individuel malformé ne doit pas faire perdre tout le flux.
            logger.warning("Entrée ignorée dans '%s' : %s", name, type(exc).__name__)
            continue

    return entries


def _extract_image_url(entry) -> Optional[str]:
    """Extrait uniquement une image déclarée nativement par le flux RSS/Atom."""
    candidates = []
    candidates.extend(getattr(entry, "media_content", []) or [])
    candidates.extend(getattr(entry, "media_thumbnail", []) or [])
    candidates.extend(getattr(entry, "enclosures", []) or [])
    for candidate in candidates:
        url = candidate.get("url") if hasattr(candidate, "get") else None
        mime_type = candidate.get("type", "") if hasattr(candidate, "get") else ""
        if url and (mime_type.startswith("image/") or "thumbnail" in str(candidate).lower() or not mime_type):
            if _is_safe_url(url):
                return url
    return None


def collect_all() -> List[Dict]:
    """Interroge toutes les sources et retourne les entrées collectées, source par source."""
    collected: List[Dict] = []
    failed_sources = 0

    for source in SOURCES:
        try:
            entries = _collect_source(source)
            collected.extend(entries)
        except Exception as exc:
            # Filet de sécurité ultime : même une erreur totalement imprévue
            # sur une source ne doit jamais interrompre la boucle globale.
            failed_sources += 1
            logger.error("Erreur inattendue sur la source '%s' : %s", source.get("name"), type(exc).__name__)
            continue

    logger.info(
        "Collecte terminée : %d entrées récupérées sur %d source(s) (%d en échec)",
        len(collected), len(SOURCES), failed_sources,
    )
    return collected
