from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Article, Base
from app.pipeline import cleanup_old_articles, _store_new_entries
from app.processing.relevance import relevance_reason
from app import pipeline


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_relevance_rejects_generic_content_before_ai():
    assert relevance_reason({"title": "Webinar: How to stay ahead", "raw_summary": "Join us"})
    assert relevance_reason({"title": "Leadership update", "raw_summary": "Company news"})
    assert relevance_reason({"title": "CVE-2026-12345", "raw_summary": "Vulnerability exploited"}) is None


def test_store_marks_rejected_without_deleting_or_calling_ai(monkeypatch):
    session = _session()
    entries = [{
        "source": "Test", "source_url": "https://example.org/webinar",
        "title": "Webinar: How to stay ahead", "raw_summary": "Company event",
        "content_hash": "rejected-hash",
    }]
    stored = _store_new_entries(session, entries)
    assert stored[0].status == "rejected_prefilter"
    monkeypatch.setattr(pipeline, "rewrite_article_async", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("IA appelée")))
    assert session.query(Article).count() == 1
    session.close()


def test_cleanup_does_not_delete_pending_inbox_article(monkeypatch):
    session = _session()
    old = datetime.utcnow() - timedelta(days=120)
    session.add_all([
        Article(source="T", source_url="https://example.org/rejected", title="Rejected", content_hash="r", status="rejected_prefilter", collected_at=old),
        Article(source="T", source_url="https://example.org/relayed", title="Relayed", content_hash="p", status="published", published=True, whatsapp_relayed=True, whatsapp_relayed_at=old, collected_at=datetime.utcnow()),
        Article(source="T", source_url="https://example.org/pending", title="Pending", content_hash="i", status="published", published=True, whatsapp_relayed=False, collected_at=old),
    ])
    session.commit()
    monkeypatch.setattr(pipeline, "get_session", lambda: session)
    monkeypatch.setattr(pipeline.settings, "rejected_retention_days", 30)
    monkeypatch.setattr(pipeline.settings, "published_retention_days", 90)
    cleanup_old_articles()
    assert session.query(Article).filter(Article.title == "Rejected").count() == 0
    assert session.query(Article).filter(Article.title == "Relayed").count() == 0
    assert session.query(Article).filter(Article.title == "Pending").count() == 1
    session.close()
