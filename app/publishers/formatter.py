"""
Mise en forme des messages par canal.
Le texte rédigé par l'IA est le même pour tous les canaux — seule
l'enrobage (embed Discord, emojis Telegram, texte brut WhatsApp) change.
"""
from datetime import datetime
from typing import Dict, List

CRITICALITY_COLOR = {
    "urgent": 0xE74C3C,   # rouge
    "digest": 0x3498DB,   # bleu
}


def build_discord_embed(article: Dict, ai_text: str) -> Dict:
    """Construit le payload d'un Rich Embed Discord."""
    color = CRITICALITY_COLOR.get(article.get("urgency", "digest"), 0x95A5A6)
    return {
        "embeds": [
            {
                "title": article.get("title", "Alerte SegenGhost Security")[:256],
                "description": ai_text[:4000],
                "color": color,
                "fields": [
                    {"name": "CVE", "value": article.get("cve_id") or "non disponible", "inline": True},
                    {"name": "CVSS", "value": str(article.get("cvss_score") or "non disponible"), "inline": True},
                    {"name": "Source", "value": article.get("source", "non disponible"), "inline": True},
                    {"name": "Zone géographique", "value": article.get("region") or "Non spécifique", "inline": True},
                ],
                "url": article.get("source_url"),
                **({"image": {"url": article["image_url"]}} if article.get("image_url") else {}),
                "footer": {"text": "SegenGhost Security"},
                "timestamp": datetime.utcnow().isoformat(),
            }
        ]
    }


def build_telegram_message(article: Dict, ai_text: str) -> str:
    """Construit le message texte destiné à Telegram (canal + admin)."""
    return (
        f"{ai_text}\n\n"
        f"📅 {datetime.utcnow().strftime('%d/%m/%Y %H:%M UTC')}"
    )


def build_whatsapp_ready_text(article: Dict, ai_text: str) -> str:
    """
    Texte prêt à copier/coller tel quel sur la chaîne WhatsApp.
    Volontairement simple : pas de markdown Telegram/Discord, juste du texte brut.
    """
    return ai_text.strip()


def build_digest_report(items: List[Dict]) -> str:
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
        lines.append(f"{i}. {emoji} {item['title']}")
        lines.append(item.get("ai_text", "").strip())
        lines.append("")

    lines.append("━━━━━━━━━━━━━━")
    lines.append(f"📅 {datetime.utcnow().strftime('%d/%m/%Y')}")
    return "\n".join(lines)
