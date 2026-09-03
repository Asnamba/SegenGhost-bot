"""
Point d'entrée de l'application SegenGhost Security.

Démarre l'API FastAPI (utile pour la supervision et le déclenchement manuel)
ainsi que le scheduler de tâches automatiques (collecte + digests).
"""
import logging

from fastapi import FastAPI, BackgroundTasks, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from sqlalchemy import text

from app.logging_config import configure_logging
from app.config import settings, validate_config
from app.database import init_db, get_session
from app.scheduler import start_scheduler, stop_scheduler
from app.pipeline import run_collect_and_urgent, run_digest
from app.web.routes import router as dashboard_router

configure_logging()
logger = logging.getLogger("segenghost.main")

app = FastAPI(title="SegenGhost Security Bot", version="0.3.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(dashboard_router)


@app.on_event("startup")
def on_startup():
    validate_config()
    init_db()
    if settings.scheduler_enabled:
        start_scheduler()
    logger.info("SegenGhost Security démarré.")


@app.on_event("shutdown")
def on_shutdown():
    stop_scheduler()
    logger.info("SegenGhost Security arrêté.")


@app.get("/")
def root():
    return RedirectResponse(url="/dashboard")


@app.get("/health")
def health():
    """
    Vérifie que le service et sa base de données répondent.
    Statut "degraded" (et non une erreur HTTP) si la base est inaccessible :
    le service reste interrogeable pour diagnostic même en cas de panne DB.
    """
    db_ok = True
    try:
        session = get_session()
        session.execute(text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        logger.error("Health check : base de données inaccessible (%s)", type(exc).__name__)
    finally:
        if "session" in locals():
            session.close()

    return {
        "status": "ok" if db_ok else "degraded",
        "project": "SegenGhost Security",
        "database": "ok" if db_ok else "unreachable",
    }


def _require_admin_token(authorization: str | None) -> None:
    expected = settings.admin_api_token
    if not expected or not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=503 if not expected else 401, detail="Authentification administrateur requise.")
    if not compare_digest(authorization[7:], expected):
        raise HTTPException(status_code=401, detail="Authentification administrateur invalide.")


@app.post("/trigger/collect")
def trigger_collect(background_tasks: BackgroundTasks, authorization: str | None = Header(default=None)):
    """Déclenche manuellement un cycle de collecte + traitement des urgences."""
    _require_admin_token(authorization)
    background_tasks.add_task(run_collect_and_urgent)
    return {"status": "collecte déclenchée"}


@app.post("/trigger/digest")
def trigger_digest(background_tasks: BackgroundTasks, authorization: str | None = Header(default=None)):
    """Déclenche manuellement la génération et publication du digest."""
    _require_admin_token(authorization)
    background_tasks.add_task(run_digest)
    return {"status": "digest déclenché"}
