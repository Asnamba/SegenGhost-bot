"""
Couche base de données — SQLAlchemy.
Deux tables principales :
- Article : chaque information brute collectée (dédoublonnage via content_hash)
- PublishedAlert : trace de chaque publication effectuée (traçabilité, anti-doublon d'envoi)
"""
import logging
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Float, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

logger = logging.getLogger("segenghost.database")

# pool_pre_ping évite l'erreur "connexion perdue" après une période d'inactivité
# prolongée (cas typique d'un bot qui tourne plusieurs jours sans interruption) :
# SQLAlchemy teste la connexion avant chaque usage et la recrée si nécessaire.
# Sans effet sur SQLite (pool à connexion unique), pertinent surtout pour PostgreSQL.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True)
    source = Column(String(255), nullable=False)          # ex: "CISA", "Microsoft Security"
    source_url = Column(String(1024), nullable=False)
    title = Column(String(1024), nullable=False)
    raw_summary = Column(Text, nullable=True)
    content_hash = Column(String(64), unique=True, index=True)  # anti-doublon

    # --- Données extraites / vérifiées (jamais reformulées par l'IA) ---
    cve_id = Column(String(32), nullable=True, index=True)
    cvss_score = Column(Float, nullable=True)
    exploited = Column(Boolean, default=False)             # présence CISA KEV / exploitation confirmée
    affected_products = Column(Text, nullable=True)
    fixed_version = Column(String(255), nullable=True)

    # --- Classification ---
    category = Column(String(64), nullable=True)            # vulnerabilite / ransomware / phishing / reglementaire ...
    urgency = Column(String(16), default="digest")           # "urgent" | "digest"
    region = Column(String(64), nullable=True, index=True)   # zone géographique ciblée détectée (ex: "Afrique")

    # --- Cycle de vie ---
    collected_at = Column(DateTime, default=datetime.utcnow)
    published = Column(Boolean, default=False)
    ai_rewritten_text = Column(Text, nullable=True)


class PublishedAlert(Base):
    __tablename__ = "published_alerts"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, nullable=False, index=True)
    channel = Column(String(32), nullable=False)  # "discord" | "telegram_channel" | "telegram_admin"
    mode = Column(String(16), nullable=False)      # "urgent" | "digest"
    sent_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)


def init_db():
    """Crée les tables si nécessaire. Une erreur ici est critique (le bot ne peut pas fonctionner sans base) — elle est journalisée puis propagée volontairement pour empêcher un démarrage silencieusement cassé."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Base de données initialisée avec succès.")
    except Exception as exc:
        logger.critical("Échec d'initialisation de la base de données : %s", type(exc).__name__)
        raise


def get_session():
    """Interface historique — ouvre une session que l'appelant doit fermer lui-même (try/finally)."""
    return SessionLocal()


@contextmanager
def session_scope():
    """
    Alternative pratique à get_session() pour du code neuf ou les tests :
    commit automatique si tout se passe bien, rollback + fermeture systématique sinon.
    N'affecte pas les appelants existants, qui continuent d'utiliser get_session().
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
