# SegenGhost Security — Bot de veille cybersécurité

Bot automatisé de collecte, rédaction et diffusion d'actualités cybersécurité,
avec dashboard web d'historique et de recherche, conforme au cahier des charges.

## Architecture

```
Sources RSS officielles → Collecte → Dédoublonnage
    → Classification (CVE / CVSS / urgence / zone géographique)
    → Rédaction IA (contrôlée, sans invention) → Validation factuelle
    → Publication Discord + Telegram (automatique)
    → Notification push admin + texte prêt pour la chaîne WhatsApp (relai manuel)
    → Stockage + Dashboard web (historique, recherche, filtres)
```

## Installation

```bash
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
# PowerShell : Copy-Item .env.example .env
# Linux/macOS : cp .env.example .env
# Remplir .env avec vos tokens (Gemini ou Anthropic, Discord, Telegram)
```

## Configuration requise

| Variable | Description |
| `DATABASE_URL` | SQLite par défaut ; passer à une URL PostgreSQL en production |
| `DISCORD_WEBHOOK_URGENT` / `DISCORD_WEBHOOK_DIGEST` | Webhooks Discord (Paramètres du salon > Intégrations) |
| `DISCORD_TOKEN` | Token du bot Discord classique, optionnel si les webhooks sont utilisés |
| `DISCORD_CHANNEL_ID` | ID de salon par défaut du bot Discord |
| `DISCORD_CHANNEL_URGENT_ID` / `DISCORD_CHANNEL_DIGEST_ID` | IDs de salons spécifiques, prioritaires sur `DISCORD_CHANNEL_ID` |
| `TELEGRAM_BOT_TOKEN` | Token obtenu via @BotFather |
| `TELEGRAM_CHANNEL_CHAT_ID` | ID du canal public SegenGhost Security |
| `TELEGRAM_ADMIN_CHAT_ID` | ID du chat privé admin (notifications push + relai WhatsApp) |
| `AI_PROVIDER` | Fournisseur IA actif : `gemini` ou `anthropic` (Gemini par défaut) |
| `GEMINI_API_KEY` | Clé API Gemini, nécessaire si `AI_PROVIDER=gemini` |
| `GEMINI_MODEL` | Modèle Gemini, `gemini-2.5-flash-lite` par défaut |
| `GROQ_API_KEY` | Clé Groq optionnelle, utilisée par le fallback prioritaire |
| `MISTRAL_API_KEY` | Clé Mistral optionnelle, utilisée par le fallback |
| `AI_PROVIDER_PRIORITY` | Ordre des providers, `groq,gemini,mistral` par défaut |
| `ANTHROPIC_API_KEY` | Clé API Claude, nécessaire si `AI_PROVIDER=anthropic` |

## Lancement

```bash
uvicorn app.main:app --reload
```

En production, lancer un seul processus avec le scheduler actif. Si plusieurs
workers sont utilisés, définir `SCHEDULER_ENABLED=false` sur les workers web et
exécuter le scheduler dans un processus séparé. Renseigner `ADMIN_API_TOKEN`,
`DASHBOARD_USERNAME` et `DASHBOARD_PASSWORD` avant toute exposition publique.

- API + dashboard sur `http://localhost:8000` (la racine `/` redirige vers `/dashboard`)
- Le scheduler démarre automatiquement : collecte toutes les 1h (configurable),
  digest publié à 8h00, 14h00 et 19h00.

## Déploiement Railway ou Render

Le projet est prévu pour un service web Python persistant, pas pour Vercel.
`Procfile`, `runtime.txt`, `railway.toml` et `render.yaml` sont inclus dans le
répertoire racine. Le serveur écoute sur `0.0.0.0` et utilise automatiquement
le port fourni par la plateforme via `PORT`. Le démarrage ne contient pas
`--reload`.

### Option Railway

1. Pousser le projet sur GitHub, puis créer un projet Railway depuis ce dépôt.
2. Ajouter un service **PostgreSQL** dans le même projet.
3. Dans le service web, renseigner les variables listées ci-dessous. Définir
  `DATABASE_URL` avec la référence Railway vers l'URL de connexion PostgreSQL
  fournie par le service, ou avec sa valeur PostgreSQL complète.
4. Conserver une seule réplique du service web. `railway.toml` fixe
  `numReplicas = 1`, car chaque processus web démarre le scheduler.
5. Configurer le health check sur `/health`. Railway utilisera le démarrage
  défini par `railway.toml` ou par le `Procfile`.

### Option Render

1. Pousser le projet sur GitHub, puis créer un **Web Service** depuis ce dépôt.
2. Utiliser `pip install -r requirements.txt` comme Build Command et
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT` comme Start Command.
3. Utiliser le Blueprint `render.yaml` avec **Apply** : il déclare le service
  web et une base PostgreSQL `segenghost-db`, tous deux en plan `free`, et
  injecte automatiquement sa `connectionString` dans `DATABASE_URL`.
4. Si la base est créée séparément, copier son URL de connexion interne dans
  `DATABASE_URL` du service web. La base PostgreSQL gratuite Render indiquée
  par la plateforme est limitée à 1 Go et expire après 30 jours sauf upgrade
  ou changement d'offre : vérifier les conditions actuelles dans Render.
5. Définir le health check sur `/health` et conserver `numInstances: 1`.
  `render.yaml` préconfigure ces paramètres et les variables d'environnement.

Le plan gratuit du Web Service peut se mettre en veille après une période
d'inactivité. Un ping externe de `/health` toutes les 10 à 14 minutes peut
réduire cette mise en veille, sans garantir la disponibilité continue ni le
fonctionnement permanent du scheduler.

PostgreSQL est déjà supporté par SQLAlchemy et `psycopg2-binary`. Pour un
premier déploiement, `Base.metadata.create_all()` crée les tables absentes,
ce qui est acceptable sur une base PostgreSQL neuve. Il faudra ajouter Alembic
avant les évolutions de schéma sur une base contenant déjà des données.

### Variables d'environnement

Variables minimales pour cette phase Discord seul :

| Variable | Valeur exemple | Rôle |
|---|---|---|
| `DATABASE_URL` | `injectée par Render` | URL PostgreSQL liée au service |
| `ADMIN_API_TOKEN` | `générer-un-token-long` | Protège les routes `/trigger/*` |
| `DASHBOARD_USERNAME` | `admin` | Utilisateur HTTP Basic du dashboard/API |
| `DASHBOARD_PASSWORD` | `mot-de-passe-long-et-unique` | Mot de passe HTTP Basic |
| `SCHEDULER_ENABLED` | `true` | Doit être `true` sur l'unique instance web |
| `AI_PROVIDER` | `gemini` | Fournisseur IA actif |
| `GEMINI_API_KEY` | `AIza...` | Rédaction IA Gemini |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | Modèle Gemini |
| `DISCORD_WEBHOOK_URGENT` | `https://discord.com/api/webhooks/...` | Publication urgente |
| `DISCORD_WEBHOOK_DIGEST` | `https://discord.com/api/webhooks/...` | Publication digest |

Les variables Telegram peuvent rester absentes ou vides. Le code les signale
par avertissement et les publishers Telegram retournent `False` sans lever
d'exception ; Discord suffit pour publier les urgences et les digests.

Discord accepte deux modes indépendants :

- si `DISCORD_TOKEN` et un ID de salon sont renseignés, le bot classique
  `discord.py` publie dans le salon en priorité ;
- sinon, si le webhook du mode demandé est renseigné, il est utilisé comme
  fallback ;
- les deux modes peuvent être configurés simultanément, le bot restant prioritaire.

Pour le mode bot, créer une application dans le [Discord Developer Portal](https://discord.com/developers/applications),
ajouter un bot, copier son token dans `DISCORD_TOKEN`, puis inviter le bot sur
le serveur avec les permissions `View Channel` et `Send Messages` (et
`Embed Links` pour les embeds). Activer le scope `bot` et l'intent privilégié
`Message Content Intent` dans le Developer Portal. Copier les IDs
des salons après avoir activé le mode développeur Discord.

Pour obtenir une clé Gemini, ouvrir [Google AI Studio](https://aistudio.google.com/apikey),
se connecter avec un compte Google, créer une clé API et la copier dans
`GEMINI_API_KEY`. Le niveau gratuit est généralement utilisable sans carte
bancaire, selon le pays et le compte ; ses quotas de requêtes et de tokens
sont limités et peuvent changer. Consultez [les limites de débit Gemini](https://ai.google.dev/gemini-api/docs/rate-limits)
et le tableau d'utilisation AI Studio. Le dépassement des quotas peut provoquer
des erreurs temporaires ou nécessiter une attente.

Pour passer à Claude, définir `AI_PROVIDER=anthropic`, renseigner
`ANTHROPIC_API_KEY` et conserver `AI_MODEL` avec le modèle Anthropic souhaité.
La clé Gemini peut alors rester présente ou être supprimée ; elle n'est pas
lue lorsque le fournisseur Anthropic est sélectionné.

Variables optionnelles, avec leurs valeurs par défaut :

| Variable | Défaut |
|---|---:|
| `AI_MODEL` | `claude-sonnet-4-6` (utilisé par Anthropic) |
| `GROQ_API_KEY` | vide |
| `MISTRAL_API_KEY` | vide |
| `AI_PROVIDER_PRIORITY` | `groq,gemini,mistral` |
| `AI_MAX_RETRIES` | `2` |
| `AI_TIMEOUT_SECONDS` | `30` |
| `CVSS_URGENT_THRESHOLD` | `8.5` |
| `COLLECT_INTERVAL_MINUTES` | `60` |
| `HTTP_TIMEOUT_SECONDS` | `15` |
| `RSS_FETCH_MAX_RETRIES` | `2` |
| `REJECTED_RETENTION_DAYS` | `30` |
| `PUBLISHED_RETENTION_DAYS` | `90` |
| `LOG_LEVEL` | `INFO` |

`PORT` est fourni automatiquement par Railway ou Render et ne doit pas être
créé manuellement. Les heures de digest restent `08:00`, `14:00` et `19:00`,
heure locale du serveur.

### Sécurité avant mise en ligne

`.gitignore` exclut `.env`, `.venv/`, `venv/`, `*.db` et `*.sqlite3`. Ne jamais
coller de secrets dans le dépôt. Le dashboard et l'API sont protégés lorsque
`DASHBOARD_USERNAME` et `DASHBOARD_PASSWORD` sont définis ; les routes
`/trigger/collect` et `/trigger/digest` exigent `Authorization: Bearer
<ADMIN_API_TOKEN>`. Le health check `/health` reste public et vérifie la
connectivité de la base, ce qui convient au contrôle automatique de Railway et
Render.

## Dashboard web et boîte de réception

Accessible sur `/dashboard` :
- Statistiques globales (total, urgentes, digest)
- Recherche texte (titre, CVE, contenu rédigé)
- Filtres : catégorie, niveau d'urgence, zone géographique ciblée, plage de dates
- Page de détail par alerte (`/dashboard/alert/{id}`) avec texte complet et lien vers la source officielle

Le dashboard est protégé par HTTP Basic avec `DASHBOARD_USERNAME` et
`DASHBOARD_PASSWORD`. La boîte de réception `/dashboard/inbox` liste les
articles traités par IA et non encore relayés manuellement vers WhatsApp. Elle
permet de copier le texte prêt à publier puis de cliquer sur **Marquer comme
relayé**, sans dépendre de Telegram.

Les articles rejetés par le pré-filtre sont conservés avec le statut
`rejected_prefilter` et restent consultables via le filtre de statut. Les
rejets sont nettoyés après `REJECTED_RETENTION_DAYS` jours ; seuls les articles
publiés et déjà relayés sont nettoyés après `PUBLISHED_RETENTION_DAYS` jours.

API JSON équivalente pour intégrations externes :
- `GET /api/alerts` (mêmes filtres que le dashboard : `q`, `category`, `urgency`, `region`, `date_from`, `date_to`)
- `GET /api/stats`

## Veille géographique ciblée

Chaque article est analysé pour détecter une zone géographique mentionnée
(ex. attaques ciblant l'Afrique, l'Europe, etc.), via `app/processing/classifier.py::detect_region`.
La liste de mots-clés par région est simple à étendre selon les besoins de veille.

## Endpoints de contrôle

- `GET /health` — vérifie que le service tourne
- `POST /trigger/collect` — déclenche manuellement un cycle de collecte
- `POST /trigger/digest` — déclenche manuellement la génération du digest

## Tests

```bash
pytest tests/ -v
```

## Ce qui a été implémenté

- ✅ Collecte RSS multi-sources (CISA, NVD, Microsoft, Talos, Cloudflare, CrowdStrike, GitHub, Infosecurity Magazine, The Register — Security & Networks, Ars Technica, Sky News Tech, Intruder.io)
- ✅ Dédoublonnage par hash de contenu
- ✅ Extraction déterministe (règles, pas d'IA) des CVE, scores CVSS, statut d'exploitation
- ✅ Classification élargie : vulnérabilité, ransomware, phishing, réglementaire, **réseaux informatiques**, général
- ✅ Détection de zone géographique ciblée (veille géographique)
- ✅ Rédaction IA strictement encadrée (prompts + validation post-génération empêchant l'altération des données factuelles)
- ✅ Publication automatique Discord (Rich Embeds) et Telegram (canal officiel)
- ✅ Notification push immédiate à l'administrateur + texte prêt à relayer sur la chaîne WhatsApp
- ✅ Digest groupé publié aux 3 créneaux définis
- ✅ Scheduler intégré (APScheduler)
- ✅ Dashboard web complet : historique, recherche multi-critères, page de détail
- ✅ API JSON d'historique/recherche
- ✅ Support PostgreSQL (changer `DATABASE_URL`, driver déjà inclus)
- ✅ Base de données avec traçabilité des publications (`PublishedAlert`)

## Reste à faire avant une mise en production

- ⬜ Renseigner les vrais tokens (Discord, Telegram, Anthropic) et tester en conditions réelles — non testé faute d'accès réseau lors du développement
- ⬜ Vérifier/ajuster les URLs des flux RSS (certaines sources officielles changent régulièrement ; l'URL d'Intruder.io notamment est à confirmer au déploiement)
- ⬜ Basculer sur PostgreSQL en production (le code le supporte déjà)
- ⬜ Ajout de sources supplémentaires (ENISA, Palo Alto, Fortinet, OWASP...)
- ⬜ Déploiement (Docker, serveur, gestion des secrets en production)
- ⬜ Authentification sur le dashboard si celui-ci est exposé publiquement (actuellement sans authentification)

## Note sur LinkedIn

LinkedIn n'expose aucun flux RSS public et son API est fortement restreinte
(accès entreprise, validation préalable). Cette source n'est donc **pas incluse**
dans la collecte automatique. Si tu veux du contenu LinkedIn, la même logique
que pour WhatsApp s'applique : relai manuel à partir des alertes générées.

## Note sur WhatsApp

Conformément au cahier des charges, **aucune automatisation directe** n'est
faite vers WhatsApp afin d'éviter tout risque de suspension de la chaîne.
Le bot transmet à l'administrateur, via notification Telegram, un texte
prêt à copier-coller manuellement sur la chaîne WhatsApp.

## Durcissement V1 (pré-audit)

Une passe de robustesse/sécurité a été appliquée sans changer l'architecture
ni les interfaces existantes. Voir le rapport détaillé fourni séparément
pour le détail complet ; résumé :

- Isolation des erreurs à tous les niveaux (une source RSS, un article ou un
  canal de publication en échec n'interrompt jamais le reste du cycle).
- Timeout + retry avec backoff exponentiel sur la collecte RSS, l'appel IA
  et les publications Discord/Telegram.
- **Correctif de sécurité critique** : les URLs de webhook Discord et d'API
  Telegram contiennent un secret (token) dans leur chemin — elles ne sont
  plus jamais loguées, y compris via la représentation texte d'une exception.
- Validation de la configuration au démarrage (avertissements clairs si des
  variables manquent, sans empêcher le démarrage en mode dégradé).
- `pool_pre_ping` sur la base de données pour éviter les erreurs de connexion
  perdue après une longue période d'exécution continue.
- Scheduler durci contre le chevauchement de jobs et l'accumulation
  d'exécutions manquées (`coalesce`, `max_instances=1`, `misfire_grace_time`).
- `.gitignore` ajouté (absent jusque-là — risque de fuite de `.env` via Git).
- Tests de résilience ajoutés (mocks uniquement, aucune dépendance à une
  vraie API externe).
