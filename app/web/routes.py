"""
Routes du dashboard web (historique et recherche des alertes) et de l'API JSON
correspondante, utilisée pour les intégrations externes ou un futur frontend enrichi.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import get_session
from app.web.history import search_articles, get_article_by_id, get_stats

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Date invalide : {value}. Format attendu : YYYY-MM-DD.")


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    urgency: str = Query(""),
    status: str = Query(""),
    region: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    session = get_session()
    try:
        articles = search_articles(
            session,
            query=q,
            category=category or None,
            urgency=urgency or None,
            status=status or None,
            region=region or None,
            date_from=_parse_date(date_from),
            date_to=_parse_date(date_to),
            published_only=False,
        )
        stats = get_stats(session)
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "articles": articles,
                "stats": stats,
                "filters": {
                    "q": q, "category": category, "urgency": urgency, "status": status,
                    "region": region, "date_from": date_from, "date_to": date_to,
                },
            },
        )
    finally:
        session.close()


@router.get("/dashboard/alert/{article_id}", response_class=HTMLResponse)
def alert_detail(request: Request, article_id: int):
    session = get_session()
    try:
        article = get_article_by_id(session, article_id, published_only=False)
        if not article:
            raise HTTPException(status_code=404, detail="Alerte introuvable.")
        return templates.TemplateResponse(
            "alert_detail.html", {"request": request, "article": article}
        )
    finally:
        session.close()


@router.get("/api/alerts")
def api_alerts(
    q: Optional[str] = None,
    category: Optional[str] = None,
    urgency: Optional[str] = None,
    region: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Historique/recherche des alertes au format JSON (pour intégrations externes)."""
    session = get_session()
    try:
        articles = search_articles(
            session,
            query=q,
            category=category,
            urgency=urgency,
            status=None,
            region=region,
            date_from=_parse_date(date_from),
            date_to=_parse_date(date_to),
            limit=limit,
            offset=offset,
        )
        return [
            {
                "id": a.id,
                "title": a.title,
                "source": a.source,
                "source_url": a.source_url,
                "cve_id": a.cve_id,
                "cvss_score": a.cvss_score,
                "exploited": a.exploited,
                "category": a.category,
                "region": a.region,
                "urgency": a.urgency,
                "collected_at": a.collected_at.isoformat() if a.collected_at else None,
                "ai_rewritten_text": a.ai_rewritten_text,
            }
            for a in articles
        ]
    finally:
        session.close()


@router.get("/api/stats")
def api_stats():
    session = get_session()
    try:
        return get_stats(session)
    finally:
        session.close()
