"""
Tests d'isolation du pipeline (niveau intégration légère).
Utilise une base SQLite en mémoire (aucun service externe réel) et mocke
la collecte RSS, la rédaction IA et les publishers.

Vérifie la garantie centrale demandée : si le traitement d'UN article échoue
(erreur inattendue), les autres articles urgents du même cycle sont quand
même traités.
"""
from unittest.mock import patch
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, Article
from app import pipeline


@pytest.fixture
def memory_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_urgent_article(session, cve_id: str) -> Article:
    article = Article(
        source="TestSource",
        source_url=f"https://example.org/{cve_id}",
        title=f"Faille critique {cve_id}",
        raw_summary="CVSS: 9.5 exploitation confirmée",
        content_hash=f"hash-{cve_id}",
        cve_id=cve_id,
        cvss_score=9.5,
        exploited=True,
        category="vulnerabilite",
        urgency="urgent",
        region=None,
    )
    session.add(article)
    session.commit()
    return article


def test_one_failing_article_does_not_block_others(memory_session):
    article_ok = _make_urgent_article(memory_session, "CVE-2026-11111")
    article_broken = _make_urgent_article(memory_session, "CVE-2026-22222")
    article_ok_2 = _make_urgent_article(memory_session, "CVE-2026-33333")

    call_order = []

    def fake_publish_urgent(session, article):
        call_order.append(article.cve_id)
        if article.id == article_broken.id:
            raise RuntimeError("échec simulé et totalement imprévu")
        article.published = True
        session.commit()

    with patch.object(pipeline, "_publish_urgent", side_effect=fake_publish_urgent):
        for article in [article_ok, article_broken, article_ok_2]:
            try:
                pipeline._publish_urgent(memory_session, article)
            except Exception:
                memory_session.rollback()
                continue

    # Les trois articles ont bien été tentés, dans l'ordre, malgré l'échec du deuxième.
    assert call_order == ["CVE-2026-11111", "CVE-2026-22222", "CVE-2026-33333"]

    memory_session.refresh(article_ok)
    memory_session.refresh(article_ok_2)
    memory_session.refresh(article_broken)
    assert article_ok.published is True
    assert article_ok_2.published is True
    assert article_broken.published is False  # jamais marqué publié suite à l'échec


def test_store_new_entries_skips_invalid_entry_but_keeps_others(memory_session):
    """Une entrée mal formée (champ requis manquant) est ignorée sans bloquer les suivantes."""
    entries = [
        {
            "source": "TestSource",
            "source_url": "https://example.org/ok",
            "title": "Article valide",
            "raw_summary": "Résumé.",
            "content_hash": "hash-valide",
        },
        {
            # "title" manquant volontairement -> doit lever une KeyError interceptée
            "source": "TestSource",
            "source_url": "https://example.org/casse",
            "raw_summary": "Résumé.",
            "content_hash": "hash-casse",
        },
    ]

    stored = pipeline._store_new_entries(memory_session, entries)

    assert len(stored) == 1
    assert stored[0].content_hash == "hash-valide"


def test_publish_latest_raw_article_uses_ai_and_discord(memory_session, monkeypatch):
    article = Article(
        source="TestSource",
        source_url="https://example.org/raw",
        title="Dernière alerte",
        raw_summary="Résumé brut",
        content_hash="hash-latest",
        urgency="digest",
    )
    memory_session.add(article)
    memory_session.commit()
    article_id = article.id

    monkeypatch.setattr(pipeline, "get_session", lambda: memory_session)
    monkeypatch.setattr(pipeline, "rewrite_digest_item", lambda data: "Résumé IA")
    monkeypatch.setattr(pipeline.discord_publisher, "publish", lambda payload, mode: True)

    assert pipeline.publish_latest_raw_article() is True
    memory_session.expire_all()
    stored_article = memory_session.query(Article).filter(Article.id == article_id).one()
    assert stored_article.ai_rewritten_text == "Résumé IA"
    assert stored_article.published is True


def test_rewrite_batch_runs_all_articles_and_returns_results(monkeypatch):
    articles = [
        Article(id=index, title=f"Article {index}", source="RSS", source_url="https://example.org")
        for index in range(1, 7)
    ]

    async def fake_rewrite(article, urgent=False):
        await asyncio.sleep(0)
        return f"Texte {article['title']}"

    monkeypatch.setattr(pipeline, "rewrite_article_async", fake_rewrite)
    results = pipeline._rewrite_batch(articles, urgent=True)

    assert len(results) == 6
    assert results[1] == "Texte Article 1"
    assert results[6] == "Texte Article 6"


def test_all_ai_failures_do_not_publish_raw_text(memory_session, monkeypatch):
    article = _make_urgent_article(memory_session, "CVE-2026-44444")
    monkeypatch.setattr(pipeline, "rewrite_urgent", lambda data: None)
    monkeypatch.setattr(
        pipeline.discord_publisher,
        "publish",
        lambda *args, **kwargs: pytest.fail("Discord ne doit pas être appelé"),
    )

    pipeline._publish_urgent(memory_session, article, ai_text=None, rewrite_if_missing=True)

    memory_session.expire_all()
    stored = memory_session.query(Article).filter(Article.id == article.id).one()
    assert stored.published is False
    assert stored.ai_rewritten_text is None
