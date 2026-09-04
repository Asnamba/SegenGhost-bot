"""Filtre déterministe de pertinence CTI avant toute consommation IA."""

# Liste volontairement simple et modifiable sans toucher au pipeline.
GENERIC_TITLE_KEYWORDS = (
    "webinar",
    "webinaire",
    "keep going",
    "how to stay ahead",
    "stay ahead",
    "best practices",
    "guide général",
    "guide general",
    "podcast",
    "événement",
    "evenement",
)

THREAT_KEYWORDS = (
    "vulnerability",
    "vulnérabilité",
    "vulnerabilite",
    "exploit",
    "attack",
    "attaque",
    "incident",
    "breach",
    "compromise",
    "ransomware",
    "phishing",
    "malware",
    "zero-day",
    "zero day",
    "cve-",
    "cybersecurity",
    "cybersécurité",
    "cybersecurite",
    "ddos",
    "data leak",
    "fuite de données",
)

RECOGNIZED_TECHNICAL_CATEGORIES = {
    "vulnerabilite",
    "ransomware",
    "phishing",
    "reseaux_informatiques",
}


def relevance_reason(entry: dict) -> str | None:
    """Retourne une raison de rejet ou None si l'article mérite l'IA."""
    title = str(entry.get("title") or "")
    lowered_title = title.lower()
    if any(keyword in lowered_title for keyword in GENERIC_TITLE_KEYWORDS):
        return "titre générique ou marketing"

    category = entry.get("category") or "general"
    text = f"{title} {entry.get('raw_summary') or ''}".lower()
    has_threat_signal = any(keyword in text for keyword in THREAT_KEYWORDS)
    has_technical_category = category in RECOGNIZED_TECHNICAL_CATEGORIES
    if category == "general" and not has_threat_signal and not has_technical_category:
        return "aucun signal de menace concrète"
    return None


def is_relevant(entry: dict) -> bool:
    return relevance_reason(entry) is None
