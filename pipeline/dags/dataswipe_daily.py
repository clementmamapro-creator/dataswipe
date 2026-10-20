"""
dataswipe_daily.py

DAG Airflow orchestrant le pipeline DataSwipe complet, une fois par jour :
  1. scrape         : lance les 3 scrapers (France Travail, WTTJ, HelloWork)
                      — échoue si le volume collecté est anormalement bas
  2. normalize      : nettoyage + déduplication inter-sources
  3. load           : insertion PostgreSQL (upsert par dedup_key)
  4. purge          : supprime les offres non revues depuis PURGE_AFTER_DAYS jours
                      — ignorée si une source a disparu de la collecte
  5. rebuild_bridge : recalcule dim_skill / job_offer_skills / job_offer_sources
  6. export_csv     : exporte les 4 CSV lus par Power BI (dossier powerbi_export)

Les données passent d'une tâche à l'autre via des fichiers JSON partagés
(volume Docker /opt/airflow/data), plutôt que via XCom — XCom est pensé pour
de petites données (quelques Ko), pas pour ~7000 offres avec description
complète. Seul un petit bilan (volumes par source) transite par XCom.

Alerte : si la variable d'environnement NTFY_TOPIC est définie, une
notification push est envoyée à chaque échec de tâche et en fin de run réussi.

⚠️ Ce DAG n'a pas pu être testé dans un vrai environnement Airflow depuis cet
outil — à valider au premier lancement manuel (Trigger DAG), tâche par tâche.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import datetime, timedelta

from airflow import DAG
from airflow.exceptions import AirflowSkipException
from airflow.operators.python import PythonOperator

logger = logging.getLogger("airflow.task")

DATA_DIR = "/opt/airflow/data"
EXPORT_DIR = "/opt/airflow/exports"  # monté sur ./powerbi_export côté PC

# Garde-fous
MIN_RAW_OFFERS = 3000     # en dessous, le scraping est jugé raté (volume habituel ~7 000)
EXPECTED_SOURCES = 3      # France Travail, WTTJ, HelloWork
PURGE_AFTER_DAYS = 14     # une offre non revue depuis 14 jours est considérée expirée


def _dsn() -> str:
    # host="postgres" : nom du service Docker (réseau interne), pas "localhost"
    return os.environ.get(
        "DATASWIPE_POSTGRES_DSN",
        "host=postgres dbname=dataswipe user=dataswipe password=changeme",
    )


def _on_failure(context) -> None:
    from pipeline.etl.maintenance import notify

    ti = context["task_instance"]
    notify(
        "DataSwipe - ECHEC",
        f"Tache '{ti.task_id}' en echec (run {context['run_id']}) : {context.get('exception')}",
    )


default_args = {
    "owner": "dataswipe",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "on_failure_callback": _on_failure,
}


def _safe_run_id(context) -> str:
    """run_id contient des ':' (ex: manual__2026-08-19T09:15:59+00:00),
    invalides dans un nom de fichier — on les neutralise."""
    return context["run_id"].replace(":", "-").replace("+", "-")


def _raw_path(run_key: str) -> str:
    return os.path.join(DATA_DIR, f"raw_offers_{run_key}.json")


def _normalized_path(run_key: str) -> str:
    return os.path.join(DATA_DIR, f"normalized_offers_{run_key}.json")


def scrape_task(**context) -> dict:
    from dotenv import load_dotenv

    from pipeline.scrapers.registry import run_all

    load_dotenv()
    os.makedirs(DATA_DIR, exist_ok=True)

    run_key = _safe_run_id(context)
    raw_offers = run_all()
    by_source = dict(Counter(o.get("source") for o in raw_offers))
    logger.info("[scrape_task] %d offres brutes collectées %s", len(raw_offers), by_source)

    # Garde-fou n°1 : un scraping quasi vide ne doit rien écrire ni déclencher de purge
    if len(raw_offers) < MIN_RAW_OFFERS:
        raise ValueError(
            f"Volume anormalement bas : {len(raw_offers)} offres (< {MIN_RAW_OFFERS}) — {by_source}"
        )

    with open(_raw_path(run_key), "w", encoding="utf-8") as f:
        json.dump(raw_offers, f, ensure_ascii=False)

    return {"total": len(raw_offers), "sources": by_source}  # petit bilan -> XCom


def normalize_task(**context) -> None:
    from pipeline.etl.normalize import normalize_offers

    run_key = _safe_run_id(context)
    with open(_raw_path(run_key), "r", encoding="utf-8") as f:
        raw_offers = json.load(f)

    final_offers, stats = normalize_offers(raw_offers)
    logger.info(
        "[normalize_task] %d -> %d offres (%d doublons retirés)",
        stats["input_count"], stats["output_count"], stats["duplicates_removed"]
    )

    with open(_normalized_path(run_key), "w", encoding="utf-8") as f:
        json.dump(final_offers, f, ensure_ascii=False)

    # Nettoyage du fichier intermédiaire, plus nécessaire
    os.remove(_raw_path(run_key))


def load_task(**context) -> None:
    from pipeline.etl.load import load_offers_via_psycopg2

    run_key = _safe_run_id(context)
    with open(_normalized_path(run_key), "r", encoding="utf-8") as f:
        final_offers = json.load(f)

    stats = load_offers_via_psycopg2(final_offers, _dsn())
    logger.info(
        "[load_task] %d insérées/mises à jour, %d ignorées, %d lots en échec",
        stats["processed"], stats["skipped"], stats["batches_failed"]
    )

    os.remove(_normalized_path(run_key))


def purge_task(**context) -> None:
    from pipeline.etl.maintenance import purge_expired

    info = context["ti"].xcom_pull(task_ids="scrape") or {}
    sources = info.get("sources", {})

    # Garde-fou n°2 : si une source n'a rien renvoyé (clé API expirée, site modifié...),
    # ses offres ne seraient plus "revues" — on ne purge pas pour ne pas les effacer à tort.
    if len(sources) < EXPECTED_SOURCES:
        logger.warning("[purge_task] purge ignorée : sources actives %s (attendu %d)", sources, EXPECTED_SOURCES)
        raise AirflowSkipException(f"Sources incomplètes : {sources}")

    deleted = purge_expired(_dsn(), PURGE_AFTER_DAYS)
    logger.info("[purge_task] %d offres expirées supprimées", deleted)


def rebuild_bridge_task(**context) -> None:
    from pipeline.etl.maintenance import rebuild_bridge_tables

    stats = rebuild_bridge_tables(_dsn())
    logger.info("[rebuild_bridge_task] %s", stats)


def export_csv_task(**context) -> None:
    from pipeline.etl.maintenance import export_powerbi_csv, notify, write_status

    counts = export_powerbi_csv(_dsn(), EXPORT_DIR)
    info = context["ti"].xcom_pull(task_ids="scrape") or {}
    write_status(EXPORT_DIR, {"exported_rows": counts, "collected": info})
    logger.info("[export_csv_task] %s", counts)

    notify(
        "DataSwipe - OK",
        f"{counts['job_offers']} offres actives, {counts['job_offer_skills']} liens competences. "
        f"CSV prets pour Power BI.",
    )


with DAG(
    dag_id="dataswipe_daily",
    description="Pipeline quotidien DataSwipe : scrape -> normalize -> load -> purge -> export Power BI",
    default_args=default_args,
    schedule="@daily",
    start_date=datetime(2026, 8, 1),
    catchup=False,
    max_active_runs=1,  # empêche 2 exécutions du DAG de tourner en même temps
    tags=["dataswipe", "sprint1", "automatisation"],
) as dag:

    scrape = PythonOperator(task_id="scrape", python_callable=scrape_task)
    normalize = PythonOperator(task_id="normalize", python_callable=normalize_task)
    load = PythonOperator(task_id="load", python_callable=load_task)
    purge = PythonOperator(task_id="purge", python_callable=purge_task)
    # none_failed : continue même si la purge a été volontairement ignorée (skipped)
    rebuild_bridge = PythonOperator(
        task_id="rebuild_bridge",
        python_callable=rebuild_bridge_task,
        trigger_rule="none_failed",
    )
    export_csv = PythonOperator(task_id="export_csv", python_callable=export_csv_task)

    scrape >> normalize >> load >> purge >> rebuild_bridge >> export_csv