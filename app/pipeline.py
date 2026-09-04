"""
Pipeline principal : collecte → dédoublonnage → classification → rédaction IA
→ validation → publication.

Deux entrées principales :
- run_collect_and_urgent() : à exécuter fréquemment (ex. toutes les 15 min),
  gère la collecte et publie IMMÉDIATEMENT les alertes urgentes.
- run_digest() : à exécuter aux créneaux 8h/14h/19h, regroupe les articles
  "digest" en attente et publie un rapport unique.

Isolation des erreurs : chaque article est traité indépendamment. Une erreur
sur UN article (IA, formatage, DB) est journalisée et n'empêche jamais le
traitement des articles suivants dans le même cycle.
"""
import logging

from app.database import get_session, Article, PublishedAlert
from app.collectors.rss_collector import collect_all
from app.processing.dedup import filter_new_entries
from app.processing.classifier import classify
from app.config import settings
from app.ai.rewriter import rewrite_urgent, rewrite_digest_item
from app.publishers.formatter import (
    build_discord_embed,
    build_telegram_message,
    build_whatsapp_ready_text,
    build_digest_report,
)
from app.publishers import discord_publisher, telegram_publisher

logger = logging.getLogger("segenghost.pipeline")


def _store_new_entries(session, entries):
    """
    Persiste les nouvelles entrées. Un article dont la classification ou
    l'insertion échoue est journalisé et ignoré, sans bloquer les suivants.
    """
    stored = []
    for entry in entries:
        try:
            classified = classify(entry, settings.cvss_urgent_threshold)
            article = Article(
                source=classified["source"],
                source_url=classified["source_url"],
                title=classified["title"],
                raw_summary=classified.get("raw_summary"),
                content_hash=classified["content_hash"],
                cve_id=classified.get("cve_id"),
                cvss_score=classified.get("cvss_score"),
                exploited=classified.get("exploited", False),
                category=classified.get("category"),
                urgency=classified.get("urgency", "digest"),
                region=classified.get("region"),
            )
            session.add(article)
            stored.append(article)
        except Exception as exc:
            logger.error(
                "Article ignoré (échec de classification/insertion) : %s — %s",
                entry.get("title", "titre inconnu"), type(exc).__name__,
            )
            continue

    try:
        session.commit()
    except Exception as exc:
        logger.error("Échec de l'enregistrement en base des nouveaux articles : %s", type(exc).__name__)
        session.rollback()
        return []

    return stored


def _article_to_dict(article: Article) -> dict:
    return {
        "title": article.title,
        "source": article.source,
        "source_url": article.source_url,
        "cve_id": article.cve_id,
        "cvss_score": article.cvss_score,
        "exploited": article.exploited,
        "category": article.category,
        "region": article.region,
        "raw_summary": article.raw_summary,
    }


def _publish_urgent(session, article: Article):
    """
    Traite une alerte urgente de bout en bout. Toute exception ici est
    interceptée : elle ne doit jamais interrompre le traitement des autres
    alertes urgentes du même cycle.
    """
    article_dict = _article_to_dict(article)

    logger.info(
        "Article #%s candidat à publication urgente : urgency=%s, published=%s, provider=%s.",
        article.id, article.urgency, article.published, settings.ai_provider,
    )
    if settings.ai_provider == "gemini" and not settings.gemini_api_key:
        logger.info("Article #%s ignoré : clé Gemini manquante (GEMINI_API_KEY).", article.id)
    elif settings.ai_provider == "anthropic" and not settings.anthropic_api_key:
        logger.info("Article #%s ignoré : clé Anthropic manquante (ANTHROPIC_API_KEY).", article.id)
    elif settings.ai_provider not in {"gemini", "anthropic"}:
        logger.info("Article #%s ignoré : fournisseur IA invalide (%s).", article.id, settings.ai_provider)

    ai_text = rewrite_urgent(article_dict)
    if ai_text is None:
        logger.error(
            "Article #%s non publié : rédaction IA indisponible ou validation factuelle échouée.",
            article.id,
        )
        return

    logger.info("Article #%s traité par IA : texte validé, publication Discord demandée.", article.id)

    article.ai_rewritten_text = ai_text

    # Chaque canal est indépendant : l'échec de l'un n'empêche pas les autres.
    discord_payload = build_discord_embed(article_dict, ai_text)
    discord_ok = discord_publisher.publish(discord_payload, mode="urgent")

    telegram_text = build_telegram_message(article_dict, ai_text)
    telegram_ok = telegram_publisher.publish_to_channel(telegram_text)

    whatsapp_text = build_whatsapp_ready_text(article_dict, ai_text)
    admin_ok = telegram_publisher.notify_admin(telegram_text, whatsapp_text)

    if not (discord_ok or telegram_ok):
        logger.error(
            "Article #%s : rédigé mais publié sur AUCUN canal (Discord et Telegram indisponibles).",
            article.id,
        )
    elif discord_ok:
        logger.info("Article #%s publié sur Discord avec succès.", article.id)
    else:
        logger.info("Article #%s non publié sur Discord : publisher indisponible ou désactivé.", article.id)

    article.published = discord_ok or telegram_ok
    for channel, success in (
        ("discord", discord_ok),
        ("telegram_channel", telegram_ok),
        ("telegram_admin", admin_ok),
    ):
        session.add(PublishedAlert(
            article_id=article.id,
            channel=channel,
            mode="urgent",
            success=success,
            error_message=None if success else "Publication échouée",
        ))
    session.commit()
    logger.info(
        "Alerte urgente traitée pour l'article #%s (%s) — discord=%s telegram=%s admin=%s",
        article.id, article.cve_id, discord_ok, telegram_ok, admin_ok,
    )


def run_collect_and_urgent():
    """À exécuter fréquemment : collecte, classe, publie les urgences."""
    session = get_session()
    try:
        logger.info("Démarrage du cycle de collecte.")
        raw_entries = collect_all()
        new_entries = filter_new_entries(session, raw_entries)
        stored_articles = _store_new_entries(session, new_entries)

        urgent_articles = [a for a in stored_articles if a.urgency == "urgent" and not a.published]
        pending_urgent = (
            session.query(Article)
            .filter(Article.urgency == "urgent", Article.published.is_(False))
            .order_by(Article.collected_at.asc())
            .all()
        )
        article_ids = {article.id for article in urgent_articles}
        urgent_articles.extend(article for article in pending_urgent if article.id not in article_ids)
        logger.info(
            "%d nouvel(le)s article(s) stocké(s), %d urgent(s) nouveaux, %d urgent(s) en attente à traiter.",
            len(stored_articles), len([a for a in stored_articles if a.urgency == "urgent"]), len(urgent_articles),
        )

        if not urgent_articles:
            logger.info("Aucune urgence non publiée à traiter après ce cycle.")

        for article in urgent_articles:
            try:
                _publish_urgent(session, article)
            except Exception as exc:
                # Filet de sécurité ultime : ne jamais laisser un article
                # bloquer le traitement des suivants dans la même liste.
                logger.error(
                    "Erreur inattendue lors du traitement de l'article #%s : %s",
                    article.id, type(exc).__name__,
                )
                session.rollback()
                continue
    except Exception as exc:
        logger.error("Erreur inattendue dans le cycle de collecte : %s", type(exc).__name__)
        session.rollback()
    finally:
        session.close()
        logger.info("Cycle de collecte terminé.")


def publish_latest_raw_article() -> bool:
    """Traite et publie sur Discord le dernier article brut non publié."""
    session = get_session()
    try:
        article = (
            session.query(Article)
            .filter(Article.published.is_(False))
            .order_by(Article.collected_at.desc(), Article.id.desc())
            .first()
        )
        if article is None:
            logger.info("Publication manuelle impossible : aucun article brut non publié.")
            return False

        logger.info("Publication manuelle demandée pour l'article brut #%s.", article.id)
        article_dict = _article_to_dict(article)
        rewrite = rewrite_urgent if article.urgency == "urgent" else rewrite_digest_item
        ai_text = rewrite(article_dict)
        if ai_text is None:
            logger.info("Publication manuelle #%s ignorée : traitement IA indisponible ou invalide.", article.id)
            return False

        article.ai_rewritten_text = ai_text
        payload = build_discord_embed(article_dict, ai_text)
        discord_ok = discord_publisher.publish(payload, mode=article.urgency or "digest")
        logger.info("Publication manuelle #%s : discord=%s.", article.id, discord_ok)
        if discord_ok:
            article.published = True
        session.commit()
        return discord_ok
    except Exception as exc:
        session.rollback()
        logger.error("Publication manuelle échouée : %s", type(exc).__name__)
        return False
    finally:
        session.close()


def run_digest():
    """À exécuter aux créneaux planifiés : regroupe et publie les articles 'digest' en attente."""
    session = get_session()
    try:
        pending = (
            session.query(Article)
            .filter(Article.urgency == "digest", Article.published.is_(False))
            .order_by(Article.collected_at.desc())
            .limit(20)
            .all()
        )

        if not pending:
            logger.info("Aucun article en attente pour le digest.")
            return

        items_for_report = []
        for article in pending:
            try:
                article_dict = _article_to_dict(article)
                ai_text = rewrite_digest_item(article_dict)
                if ai_text is None:
                    logger.warning(
                        "Item digest #%s exclu (rédaction IA indisponible ou validation échouée).",
                        article.id,
                    )
                    continue

                article.ai_rewritten_text = ai_text
                items_for_report.append({
                    "title": article.title,
                    "category": article.category,
                    "region": article.region,
                    "ai_text": ai_text,
                })
            except Exception as exc:
                logger.error(
                    "Item digest #%s ignoré suite à une erreur inattendue : %s",
                    article.id, type(exc).__name__,
                )
                continue

        if not items_for_report:
            logger.warning("Digest annulé : aucun item n'a passé la rédaction/validation IA.")
            return

        report_text = build_digest_report(items_for_report)
        telegram_ok = telegram_publisher.publish_to_channel(report_text)
        admin_ok = telegram_publisher.notify_admin(report_text, report_text)

        discord_payload = {
            "embeds": [{
                "title": "SegenGhost Security — Digest",
                "description": report_text[:4000],
                "color": 0x3498DB,
            }]
        }
        discord_ok = discord_publisher.publish(discord_payload, mode="digest")

        if discord_ok or telegram_ok:
            for article in pending:
                if article.ai_rewritten_text:
                    article.published = True
                    for channel, success in (
                        ("discord", discord_ok),
                        ("telegram_channel", telegram_ok),
                        ("telegram_admin", admin_ok),
                    ):
                        session.add(PublishedAlert(
                            article_id=article.id,
                            channel=channel,
                            mode="digest",
                            success=success,
                            error_message=None if success else "Publication échouée",
                        ))
            session.commit()
        else:
            logger.error("Digest non marqué comme publié : aucun canal principal n'a accepté le rapport.")

        logger.info("Digest publié avec %d élément(s).", len(items_for_report))
    except Exception as exc:
        logger.error("Erreur inattendue dans le cycle de digest : %s", type(exc).__name__)
        session.rollback()
    finally:
        session.close()
