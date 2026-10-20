"""
maintenance.py

Tâches d'exploitation du pipeline DataSwipe, exécutables DANS le conteneur
Airflow (psycopg2 direct : pas de docker exec ni de psql, contrairement à
build_powerbi_tables.py qui reste utilisable à la main depuis le PC) :

  - purge_expired()          : supprime les offres non revues depuis N jours
                               (collected_at est rafraîchi à chaque upsert,
                               il sert donc de "dernière fois vue")
  - rebuild_bridge_tables()  : recalcule dim_skill, job_offer_skills et
                               job_offer_sources (modèle en étoile Power BI)
  - export_powerbi_csv()     : exporte les 4 tables en CSV UTF-8, écriture
                               atomique (fichier .tmp puis remplacement)
  - notify()                 : notification optionnelle via ntfy.sh si la
                               variable d'environnement NTFY_TOPIC est définie
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

logger = logging.getLogger("dataswipe.etl.maintenance")

EXPORT_TABLES = ["job_offers", "dim_skill", "job_offer_skills", "job_offer_sources"]

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS dim_skill (
    skill    TEXT PRIMARY KEY,
    category TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_offer_skills (
    dedup_key TEXT NOT NULL REFERENCES job_offers(dedup_key) ON DELETE CASCADE,
    skill     TEXT NOT NULL,
    PRIMARY KEY (dedup_key, skill)
);

CREATE TABLE IF NOT EXISTS job_offer_sources (
    dedup_key TEXT NOT NULL REFERENCES job_offers(dedup_key) ON DELETE CASCADE,
    source    TEXT NOT NULL,
    PRIMARY KEY (dedup_key, source)
);
"""


@contextmanager
def _connect(dsn: str):
    """Connexion UTF-8, commit si tout va bien, rollback sinon, fermeture dans tous les cas."""
    conn = psycopg2.connect(dsn)
    try:
        conn.set_client_encoding("UTF8")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def purge_expired(dsn: str, days: int) -> int:
    """Supprime les offres dont collected_at est plus ancien que `days` jours.
    Les lignes des tables de liaison partent en cascade. Retourne le nombre supprimé."""
    with _connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM job_offers WHERE collected_at < now() - make_interval(days => %s)",
            (days,),
        )
        deleted = cur.rowcount
    logger.info("[purge] %d offres supprimées (non revues depuis %d jours)", deleted, days)
    return deleted


def _as_sources(offer: dict[str, Any]) -> list[str]:
    raw = offer.get("merged_sources")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = [raw]
    sources = [s for s in (raw or []) if s]
    if not sources and offer.get("source"):
        sources = [offer["source"]]
    return sources


def rebuild_bridge_tables(dsn: str) -> dict[str, int]:
    """Recalcule dim_skill, job_offer_skills et job_offer_sources en une seule
    transaction : Power BI ne voit jamais un état à moitié reconstruit."""
    from pipeline.matching.extract_skills import get_offer_skills
    from pipeline.matching.skills_taxonomy import ALL_SKILLS, SKILLS_TAXONOMY

    valid_skills = set(ALL_SKILLS)

    with _connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLES_SQL)

            dim_rows = [
                (skill, category)
                for category, skills in SKILLS_TAXONOMY.items()
                for skill in skills
            ]
            execute_values(
                cur,
                "INSERT INTO dim_skill (skill, category) VALUES %s "
                "ON CONFLICT (skill) DO UPDATE SET category = EXCLUDED.category",
                dim_rows,
            )

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM job_offers")
            offers = [dict(r) for r in cur.fetchall()]

        skill_rows: list[tuple[str, str]] = []
        source_rows: list[tuple[str, str]] = []
        for offer in offers:
            key = offer.get("dedup_key")
            if not key:
                continue
            for skill in get_offer_skills(offer):
                if skill in valid_skills:
                    skill_rows.append((key, skill))
            for source in _as_sources(offer):
                source_rows.append((key, source))

        with conn.cursor() as cur:
            cur.execute("TRUNCATE job_offer_skills, job_offer_sources")
            execute_values(
                cur,
                "INSERT INTO job_offer_skills (dedup_key, skill) VALUES %s ON CONFLICT DO NOTHING",
                skill_rows,
                page_size=1000,
            )
            execute_values(
                cur,
                "INSERT INTO job_offer_sources (dedup_key, source) VALUES %s ON CONFLICT DO NOTHING",
                source_rows,
                page_size=1000,
            )

    stats = {
        "offers": len(offers),
        "dim_skill": len(dim_rows),
        "job_offer_skills": len(skill_rows),
        "job_offer_sources": len(source_rows),
    }
    logger.info("[bridge] %s", stats)
    return stats


def export_powerbi_csv(dsn: str, out_dir: str) -> dict[str, int]:
    """Exporte les 4 tables en CSV UTF-8 (en-tête inclus) dans out_dir.
    Chaque fichier est écrit en .tmp puis renommé : Power BI ne lit jamais
    un fichier à moitié écrit."""
    os.makedirs(out_dir, exist_ok=True)
    counts: dict[str, int] = {}

    with _connect(dsn) as conn, conn.cursor() as cur:
        for table in EXPORT_TABLES:
            final_path = os.path.join(out_dir, f"{table}.csv")
            tmp_path = final_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8", newline="") as f:
                cur.copy_expert(
                    f"COPY (SELECT * FROM {table}) TO STDOUT WITH (FORMAT csv, HEADER true)", f
                )
            counts[table] = cur.rowcount
            os.replace(tmp_path, final_path)

    logger.info("[export] %s -> %s", counts, out_dir)
    return counts


def write_status(out_dir: str, info: dict[str, Any]) -> None:
    """Dépose pipeline_status.json à côté des CSV : date et bilan du dernier run réussi."""
    info = {"last_success_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), **info}
    path = os.path.join(out_dir, "pipeline_status.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    os.replace(path + ".tmp", path)


def notify(title: str, message: str) -> None:
    """Notification push via ntfy.sh, uniquement si NTFY_TOPIC est défini.
    Ne fait jamais échouer le pipeline."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": title},  # ASCII uniquement dans les en-têtes HTTP
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[notify] envoi impossible : %s", exc)