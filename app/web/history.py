"""
Historique et recherche des alertes.
Fournit des fonctions de requête réutilisables par le dashboard web et l'API,
pour consulter les publications passées avec filtres (texte, catégorie,
urgence, région, dates).
"""
from datetime import datetime
from typing import Optional, List, Dict

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import Article


def search_articles(
    session: Session,
    query: Optional[str] = None,
    category: Optional[str] = None,
    urgency: Optional[str] = None,
    region: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    published_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> List[Article]:
    """Recherche paginée dans l'historique des articles/alertes."""
    q = session.query(Article)

    if published_only:
        q = q.filter(Article.published.is_(True))

    if query:
        like_pattern = f"%{query}%"
        q = q.filter(
            or_(
                Article.title.ilike(like_pattern),
                Article.cve_id.ilike(like_pattern),
                Article.ai_rewritten_text.ilike(like_pattern),
            )
        )

    if category:
        q = q.filter(Article.category == category)

    if urgency:
        q = q.filter(Article.urgency == urgency)

    if region:
        q = q.filter(Article.region == region)

    if date_from:
        q = q.filter(Article.collected_at >= date_from)

    if date_to:
        q = q.filter(Article.collected_at < date_to.replace(hour=23, minute=59, second=59, microsecond=999999))

    return (
        q.order_by(Article.collected_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_article_by_id(session: Session, article_id: int, published_only: bool = True) -> Optional[Article]:
    query = session.query(Article).filter(Article.id == article_id)
    if published_only:
        query = query.filter(Article.published.is_(True))
    return query.first()


def get_stats(session: Session) -> Dict:
    """Statistiques globales affichées en en-tête du dashboard."""
    total = session.query(Article).filter(Article.published.is_(True)).count()
    urgent = session.query(Article).filter(
        Article.published.is_(True), Article.urgency == "urgent"
    ).count()
    digest = total - urgent

    regions = (
        session.query(Article.region)
        .filter(Article.published.is_(True), Article.region.isnot(None))
        .distinct()
        .all()
    )
    categories = (
        session.query(Article.category)
        .filter(Article.published.is_(True), Article.category.isnot(None))
        .distinct()
        .all()
    )

    return {
        "total": total,
        "urgent": urgent,
        "digest": digest,
        "regions": sorted({r[0] for r in regions}),
        "categories": sorted({c[0] for c in categories}),
    }
