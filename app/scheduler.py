"""
Planification des tâches automatiques :
- collecte + publication urgente : toutes les N minutes (configurable)
- digest : aux heures définies (8h, 14h, 19h par défaut), heure locale du serveur

Robustesse (pertinent après plusieurs jours d'exécution continue) :
- max_instances=1 (déjà le défaut APScheduler, explicité ici) : empêche
  qu'une exécution encore en cours ne soit relancée en parallèle si un cycle
  prend plus de temps que l'intervalle prévu.
- coalesce=True : si plusieurs exécutions ont été manquées (ex. process
  suspendu un moment), elles sont fusionnées en une seule au réveil plutôt
  que rejouées en rafale.
- misfire_grace_time large : une exécution retardée de quelques minutes
  s'exécute quand même, au lieu d'être silencieusement abandonnée.
- un listener journalise toute exception de job non interceptée en amont —
  filet de sécurité, sachant que pipeline.py capture déjà ses propres erreurs.
"""
import logging

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.pipeline import run_collect_and_urgent, run_digest

logger = logging.getLogger("segenghost.scheduler")

JOB_DEFAULTS = {
    "coalesce": True,
    "max_instances": 1,
    "misfire_grace_time": 300,  # 5 minutes de tolérance avant d'abandonner une exécution manquée
}

scheduler = BackgroundScheduler(job_defaults=JOB_DEFAULTS)


def _on_job_event(event):
    if event.exception:
        logger.error(
            "Job planifié '%s' terminé en erreur non interceptée en amont : %s",
            event.job_id, type(event.exception).__name__,
        )
    else:
        logger.debug("Job planifié '%s' exécuté avec succès.", event.job_id)


def start_scheduler():
    scheduler.add_listener(_on_job_event, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)

    # Collecte régulière + traitement des urgences
    scheduler.add_job(
        run_collect_and_urgent,
        "interval",
        minutes=settings.collect_interval_minutes,
        id="collect_and_urgent",
        replace_existing=True,
    )

    # Un job cron par créneau de digest défini dans la config
    for time_str in settings.digest_times:
        hour, minute = time_str.split(":")
        scheduler.add_job(
            run_digest,
            CronTrigger(hour=int(hour), minute=int(minute)),
            id=f"digest_{time_str}",
            replace_existing=True,
        )

    scheduler.start()
    logger.info(
        "Scheduler démarré : collecte toutes les %d min, digests à %s",
        settings.collect_interval_minutes,
        ", ".join(settings.digest_times),
    )


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler arrêté proprement.")
