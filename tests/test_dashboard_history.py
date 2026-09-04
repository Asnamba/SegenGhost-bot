from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Article, Base
from app.web.history import get_stats, search_articles


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_dashboard_status_filters_and_stats_include_all_articles():
    session = _session()
    session.add_all([
        Article(
            source="RSS", source_url="https://example.org/raw", title="Brut",
            content_hash="raw", urgency="digest", collected_at=datetime.utcnow(),
        ),
        Article(
            source="RSS", source_url="https://example.org/ai", title="IA",
            content_hash="ai", urgency="digest", ai_rewritten_text="Résumé IA",
            collected_at=datetime.utcnow(),
        ),
        Article(
            source="RSS", source_url="https://example.org/published", title="Publié",
            content_hash="published", urgency="urgent", ai_rewritten_text="Alerte",
            published=True, collected_at=datetime.utcnow(),
        ),
    ])
    session.commit()

    assert len(search_articles(session, published_only=False)) == 3
    assert [article.title for article in search_articles(session, status="raw", published_only=False)] == ["Brut"]
    assert [article.title for article in search_articles(session, status="ai", published_only=False)] == ["IA"]
    assert [article.title for article in search_articles(session, status="published", published_only=False)] == ["Publié"]

    stats = get_stats(session)
    assert stats["total_collected"] == 3
    assert stats["ai_processed"] == 2
    assert stats["published"] == 1
    assert stats["urgent"] == 1
    session.close()
