"""
Tests unitaires du module de classification.
Vérifie que l'extraction CVE/CVSS et la logique d'urgence sont correctes,
puisque c'est le cœur de la fiabilité factuelle du projet.
"""
from app.processing.classifier import extract_cve, extract_cvss, is_exploited, classify, detect_region


def test_extract_cve_found():
    text = "Une vulnérabilité critique CVE-2026-12345 affecte plusieurs produits."
    assert extract_cve(text) == "CVE-2026-12345"


def test_extract_cve_not_found():
    assert extract_cve("Aucun identifiant ici.") is None


def test_extract_cvss():
    text = "Le score CVSS: 9.8 indique une sévérité critique."
    assert extract_cvss(text) == 9.8


def test_is_exploited_true():
    assert is_exploited("This vulnerability is actively exploited in the wild.") is True


def test_is_exploited_false():
    assert is_exploited("No known exploitation at this time.") is False


def test_classify_urgent_by_cvss():
    entry = {"title": "Faille critique", "raw_summary": "CVSS: 9.1 sur un serveur exposé."}
    result = classify(entry, cvss_urgent_threshold=8.5)
    assert result["urgency"] == "urgent"
    assert result["cvss_score"] == 9.1


def test_classify_digest_by_default():
    entry = {"title": "Bonnes pratiques", "raw_summary": "Conseils généraux de configuration."}
    result = classify(entry, cvss_urgent_threshold=8.5)
    assert result["urgency"] == "digest"


def test_detect_region_afrique():
    text = "A new phishing campaign targeting banks in Nigeria and Kenya."
    assert detect_region(text) == "Afrique"


def test_detect_region_none_when_unspecified():
    assert detect_region("Generic advisory with no location mentioned.") is None


def test_classify_includes_region():
    entry = {"title": "Ransomware campaign hits banks in Nigeria", "raw_summary": "CVSS: 9.0 actively exploited."}
    result = classify(entry, cvss_urgent_threshold=8.5)
    assert result["region"] == "Afrique"
    assert result["urgency"] == "urgent"


def test_classify_network_category():
    entry = {"title": "Major router outage disrupts ISP network", "raw_summary": "A misconfiguration on core routers caused a network outage."}
    result = classify(entry, cvss_urgent_threshold=8.5)
    assert result["category"] == "reseaux_informatiques"
