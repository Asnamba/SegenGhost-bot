"""
Liste des sources officielles et médias techniques surveillés.
Chaque source est un flux RSS/Atom public. Certaines organisations n'exposent
pas toujours un flux RSS stable — ceux-ci sont à vérifier/ajuster en fonction
de la disponibilité réelle au moment du déploiement.

Note sur LinkedIn : aucun flux RSS public n'existe pour LinkedIn et son API
est fortement restreinte (accès entreprise, validation préalable). Cette
source n'est donc pas automatisable simplement et reste hors périmètre
technique de la collecte automatique.
"""

SOURCES = [
    # --- Sources officielles / CERT ---
    {"name": "CISA", "url": "https://www.cisa.gov/cybersecurity-advisories/all.xml"},
    {"name": "CISA KEV", "url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog.xml"},

    # --- Éditeurs / vendeurs sécurité ---
    {"name": "Microsoft Security", "url": "https://api.msrc.microsoft.com/cvrf/v2.0/atom"},
    {"name": "Cisco Talos", "url": "https://blog.talosintelligence.com/rss/"},
    {"name": "Cloudflare Blog", "url": "https://blog.cloudflare.com/rss/"},
    {"name": "CrowdStrike", "url": "https://www.crowdstrike.com/blog/feed/"},
    {"name": "GitHub Security Advisories", "url": "https://github.com/advisories.atom"},
    {"name": "The Hacker News", "url": "https://feeds.feedburner.com/TheHackersNews"},

    # --- Médias techniques et cybersécurité (ajout veille élargie) ---
    {"name": "Infosecurity Magazine", "url": "https://www.infosecurity-magazine.com/rss/news/"},
    {"name": "The Register — Security", "url": "https://www.theregister.com/security/headlines.atom"},
    {"name": "The Register — Networks", "url": "https://www.theregister.com/on_prem/networks/headlines.atom"},
    {"name": "Ars Technica — Security", "url": "https://feeds.arstechnica.com/arstechnica/security"},
    {"name": "Sky News — Technology", "url": "https://feeds.skynews.com/feeds/rss/technology.xml"},
    {"name": "Intruder.io Blog", "url": "https://www.intruder.io/blog/rss.xml"},  # URL à vérifier au déploiement
]

