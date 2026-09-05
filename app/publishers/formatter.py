"""
Mise en forme des messages par canal.
Le texte rédigé par l'IA est le même pour tous les canaux — seule
l'enrobage (embed Discord, emojis Telegram, texte brut WhatsApp) change.
"""
import re
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional, Union

from app.config import settings

Article = Dict[str, object]
ArticleText = Union[str, Mapping[str, object]]
OptionalArticleText = Optional[ArticleText]


def _summary_text(ai_text: OptionalArticleText) -> str:
    """
    Ne retourne QUE le texte réellement rédigé par l'IA. Ne doit jamais
    retomber sur raw_summary : un texte IA manquant doit se traduire par
    une chaîne vide, jamais par la republication du résumé brut de la source.
    """
    if isinstance(ai_text, Mapping):
        value = ai_text.get("ai_text")
        return value if isinstance(value, str) else ""
    return ai_text if isinstance(ai_text, str) else ""


def extract_cvss_from_text(text: Optional[str]) -> Optional[str]:
    """Extrait le score CVSS (ex: 8.8) depuis le résumé si absent du dictionnaire."""
    if not isinstance(text, str) or not text:
        return None
    pattern = r"CVSS(?:\s*v?\d+(?:\.\d+)?)?\s*(?:score)?\s*[:\-]?\s*(\d+(?:\.\d+)?)"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else None


def build_discord_embed(article: Article, ai_text: OptionalArticleText, mode: str = "digest") -> Dict[str, object]:
    """Construit le payload d'un Rich Embed Discord."""
    timestamp = datetime.now(timezone.utc)
    summary_content = _summary_text(ai_text)

    title = article.get("title") or "Alerte SegenGhost Security"
    source = article.get("source") or "non disponible"
    cve = article.get("cve_id") or "non disponible"
    region = article.get("region") or "Non spécifique"
    source_url = article.get("source_url")
    image_url = article.get("image_url")

    # Récupération prioritaire dans article, puis secours via Regex dans le résumé
    cvss_val = article.get("cvss_score")
    if cvss_val is None or (isinstance(cvss_val, str) and cvss_val.strip().lower() == "non disponible"):
        cvss_val = extract_cvss_from_text(summary_content) or extract_cvss_from_text(str(article.get("raw_summary") or ""))

    cvss_display = str(cvss_val) if cvss_val is not None else "non disponible"

    return {
        "embeds": [
            {
                "title": str(title)[:256],
                "description": summary_content[:4000],
                "color": 0x3498DB,
                "fields": [
                    {"name": "CVE", "value": str(cve), "inline": True},
                    {"name": "CVSS", "value": cvss_display, "inline": True},
                    {"name": "Source", "value": str(source), "inline": True},
                    {"name": "Zone géographique", "value": str(region), "inline": False},
                ],
                "url": str(source_url) if source_url else None,
                **({"image": {"url": str(image_url)}} if image_url else {}),
                "footer": {
                    "text": f"SegenGhost Security • {timestamp.strftime('%d/%m/%Y %H:%M UTC')}",
                    **({"icon_url": settings.discord_bot_icon_url} if settings.discord_bot_icon_url else {}),
                },
                "timestamp": timestamp.isoformat(),
            }
        ]
    }


def build_telegram_message(article: Article, ai_text: OptionalArticleText) -> str:
    """Construit le message texte destiné à Telegram (canal + admin)."""
    return (
        f"{_summary_text(ai_text)}\n\n"
        f"📅 {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}"
    )


def build_whatsapp_ready_text(article: Article, ai_text: OptionalArticleText) -> str:
    """
    Texte prêt à copier/coller tel quel sur la chaîne WhatsApp.
    Volontairement simple : pas de markdown Telegram/Discord, juste du texte brut.
    """
    return _summary_text(ai_text).strip()


def build_digest_report(items: List[Article]) -> str:
    """Assemble plusieurs résumés d'items en un seul rapport digest."""
    if not items:
        return "🛡️ SEGEN GHOST SECURITY — Digest\nAucune nouvelle actualité notable sur cette période."

    lines = [
        "🛡️ SEGEN GHOST SECURITY",
        "Daily Cybersecurity Digest",
        "━━━━━━━━━━━━━━",
    ]
    for i, item in enumerate(items, start=1):
        emoji = {
            "vulnerabilite": "🚨", "ransomware": "🦠", "phishing": "🎣",
            "reglementaire": "📜", "reseaux_informatiques": "🌐",
        }.get(item.get("category"), "🔐")
        title = str(item.get("title") or "Alerte sans titre")
        ai_text = item.get("ai_text")
        lines.append(f"{i}. {emoji} {title}")
        lines.append(ai_text.strip() if isinstance(ai_text, str) else "")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━")
    lines.append(f"📅 {datetime.now(timezone.utc).strftime('%d/%m/%Y')}")
    return "\n".join(lines)
