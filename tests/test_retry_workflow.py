from unittest.mock import patch

import asyncio
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import pipeline
from app.database import Article, Base
from app.web.history import get_inbox_articles


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _article(session, *, status="raw", retry_count=0, urgency="urgent"):
    article = Article(
        source="Test RSS",
        source_url="https://example.org/article",
        title="Faille de test",
        raw_summary="Résumé brut non vérifié",
        content_hash=f"hash-{status}-{retry_count}-{urgency}",
        cve_id="CVE-2026-12345",
        cvss_score=9.1,
        category="vulnerabilite",
        region="Europe",
        urgency=urgency,
        status=status,
        retry_count=retry_count,
    )
    session.add(article)
    session.commit()
    return article


def test_ai_failure_is_pending_retry_and_never_published(monkeypatch):
    session = _session()
    article = _article(session)
    monkeypatch.setattr(pipeline.settings, "ai_max_retry_cycles", 3)
    with patch.object(pipeline.discord_publisher, "publish") as discord, \
         patch.object(pipeline.telegram_publisher, "publish_to_channel") as telegram, \
         patch.object(pipeline.telegram_publisher, "notify_admin") as admin:
        pipeline._publish_urgent(session, article, ai_text=None, rewrite_if_missing=False)
    session.refresh(article)
    assert article.status == "pending_retry"
    assert article.retry_count == 1
    discord.assert_not_called()
    telegram.assert_not_called()
    admin.assert_not_called()
    session.close()


def test_pending_retry_success_publishes_and_preserves_urgent_mode(monkeypatch):
    session = _session()
    article = _article(session, status="pending_retry", retry_count=1, urgency="urgent")
    monkeypatch.setattr(pipeline, "_publish_safely", lambda publisher, label, *args, **kwargs: publisher(*args, **kwargs))
    with patch.object(pipeline.discord_publisher, "publish", return_value=True) as discord, \
         patch.object(pipeline.telegram_publisher, "publish_to_channel", return_value=False), \
         patch.object(pipeline.telegram_publisher, "notify_admin", return_value=False):
        pipeline._publish_urgent(session, article, ai_text="Résumé IA validé CVE-2026-12345", rewrite_if_missing=False)
    session.refresh(article)
    assert article.status == "published"
    assert article.published is True
    discord.assert_called_once()
    assert discord.call_args.kwargs["mode"] == "urgent"
    session.close()


def test_permanent_failure_never_retries_or_calls_any_publisher(monkeypatch):
    session = _session()
    article = _article(session, status="pending_retry", retry_count=2)
    monkeypatch.setattr(pipeline.settings, "ai_max_retry_cycles", 3)
    with patch.object(pipeline.discord_publisher, "publish") as discord, \
         patch.object(pipeline.telegram_publisher, "publish_to_channel") as telegram, \
         patch.object(pipeline.telegram_publisher, "notify_admin") as admin:
        pipeline._publish_urgent(session, article, ai_text=None, rewrite_if_missing=False)
        session.refresh(article)
        assert article.status == "failed_permanently"
        assert article.retry_count == 3
        pipeline._publish_urgent(session, article, ai_text="ne doit pas être utilisé", rewrite_if_missing=False)
    discord.assert_not_called()
    telegram.assert_not_called()
    admin.assert_not_called()
    session.close()


def test_failed_permanently_is_private_inbox_content_with_manual_badge():
    session = _session()
    article = _article(session, status="failed_permanently", retry_count=3, urgency="digest")
    assert get_inbox_articles(session) == [article]

    environment = Environment(loader=FileSystemLoader("app/templates"))
    rendered = environment.get_template("inbox.html").render(articles=[article])
    assert "Non traité par l'IA — contenu brut, vérification manuelle requise" in rendered
    assert "Résumé brut non vérifié" in rendered
    session.close()


def test_pending_retry_urgent_is_sent_to_urgent_rewriter():
    session = _session()
    article = _article(session, status="pending_retry", retry_count=1, urgency="urgent")
    calls = []

    async def fake_rewrite(article_data, urgent=False):
        calls.append(urgent)
        return None

    with patch.object(pipeline, "rewrite_article_async", side_effect=fake_rewrite):
        results = pipeline._rewrite_batch([article], urgent=True)
    assert calls == [True]
    assert results[article.id] is None
    session.close()
