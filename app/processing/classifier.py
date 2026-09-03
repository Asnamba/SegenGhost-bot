"""
Analyse et classification des entrées collectées.

Ce module extrait des données FACTUELLES depuis le texte source (CVE, score
CVSS, mots-clés d'exploitation) par des règles déterministes — jamais par
l'IA — afin de garantir que ces informations techniques ne peuvent pas être
altérées lors de l'étape de rédaction.
"""
import re
from typing import Dict, Optional

CVE_PATTERN = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)
CVSS_PATTERN = re.compile(r"CVSS[:\s]*([0-9]{1,2}\.[0-9])", re.IGNORECASE)

EXPLOITATION_KEYWORDS = [
    "actively exploited", "exploited in the wild", "exploitation confirmed",
    "known exploited", "kev", "zero-day", "0-day", "en cours d'exploitation",
]

RANSOMWARE_KEYWORDS = ["ransomware", "rançongiciel", "encryption attack", "extortion"]
PHISHING_KEYWORDS = ["phishing", "hameçonnage", "credential harvesting"]
REGULATORY_KEYWORDS = ["regulation", "compliance", "directive", "réglementation", "loi"]
NETWORK_KEYWORDS = [
    "router", "routeur", "switch", "commutateur", "firewall", "pare-feu",
    "vpn", "dns", "bgp", "ddos", "network outage", "panne réseau",
    "réseau informatique", "infrastructure réseau", "network infrastructure",
    "protocole réseau", "wi-fi", "wifi", "5g", "fibre optique", "load balancer",
    "network misconfiguration", "isp", "fournisseur d'accès", "latence",
    "bande passante", "network breach",
]

# Veille géographique ciblée — mots-clés déclenchant l'étiquette régionale.
# Extensible : ajouter d'autres zones/pays selon les besoins de la veille.
REGION_KEYWORDS = {
    "Afrique": [
        "africa", "afrique", "nigeria", "kenya", "south africa", "afrique du sud",
        "ghana", "senegal", "sénégal", "côte d'ivoire", "ivory coast", "morocco",
        "maroc", "egypt", "égypte", "tunisia", "tunisie", "algeria", "algérie",
        "cameroon", "cameroun", "ethiopia", "éthiopie", "rwanda", "uganda", "ouganda",
    ],
    "Europe": [
        "europe", "european union", "union européenne", "france", "germany",
        "allemagne", "spain", "espagne", "italy", "italie", "uk", "royaume-uni",
    ],
    "Amérique du Nord": [
        "united states", "états-unis", "usa", "canada", "north america",
    ],
    "Asie": [
        "china", "chine", "japan", "japon", "india", "inde", "asia", "asie",
        "singapore", "singapour", "south korea", "corée du sud",
    ],
}


def extract_cve(text: str) -> Optional[str]:
    match = CVE_PATTERN.search(text or "")
    return match.group(0).upper() if match else None


def extract_cvss(text: str) -> Optional[float]:
    match = CVSS_PATTERN.search(text or "")
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def is_exploited(text: str) -> bool:
    lowered = (text or "").lower()
    return any(kw in lowered for kw in EXPLOITATION_KEYWORDS)


def detect_category(text: str) -> str:
    lowered = (text or "").lower()
    if any(kw in lowered for kw in RANSOMWARE_KEYWORDS):
        return "ransomware"
    if any(kw in lowered for kw in PHISHING_KEYWORDS):
        return "phishing"
    if any(kw in lowered for kw in REGULATORY_KEYWORDS):
        return "reglementaire"
    if extract_cve(text):
        return "vulnerabilite"
    if any(kw in lowered for kw in NETWORK_KEYWORDS):
        return "reseaux_informatiques"
    return "general"


def detect_region(text: str) -> Optional[str]:
    """
    Détecte une zone géographique ciblée mentionnée dans le texte.
    Retourne le premier nom de région dont un mot-clé est trouvé, ou None
    si aucune zone spécifique n'est identifiée (portée jugée globale/générale).
    """
    lowered = (text or "").lower()
    for region_name, keywords in REGION_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return region_name
    return None


def classify(entry: Dict, cvss_urgent_threshold: float) -> Dict:
    """
    Enrichit une entrée collectée avec les champs analysés :
    cve_id, cvss_score, exploited, category, urgency.
    """
    full_text = f"{entry.get('title', '')} {entry.get('raw_summary', '')}"

    cve_id = extract_cve(full_text)
    cvss_score = extract_cvss(full_text)
    exploited = is_exploited(full_text)
    category = detect_category(full_text)
    region = detect_region(full_text)

    is_urgent = (
        (cvss_score is not None and cvss_score >= cvss_urgent_threshold)
        or exploited
        or category == "ransomware"
        or "zero-day" in full_text.lower()
        or "0-day" in full_text.lower()
    )

    entry.update({
        "cve_id": cve_id,
        "cvss_score": cvss_score,
        "exploited": exploited,
        "category": category,
        "region": region,
        "urgency": "urgent" if is_urgent else "digest",
    })
    return entry
