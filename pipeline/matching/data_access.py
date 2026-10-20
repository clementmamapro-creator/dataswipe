"""
data_access.py

Récupère les offres depuis PostgreSQL pour le matching et l'assistance IA.
Réutilise l'approche `docker-compose exec psql` déjà validée dans
etl/load.py plutôt qu'un driver Python (pg8000 a posé un bug
d'authentification SCRAM non résolu sur cet environnement Windows/Python
3.14 — voir load.py).

On récupère les données sérialisées en JSON côté PostgreSQL (row_to_json),
pour éviter les soucis de parsing CSV avec les colonnes de type tableau
(skills, merged_sources).
"""

from __future__ import annotations

import json
import logging
import subprocess

logger = logging.getLogger("dataswipe.matching.data_access")

OFFER_COLUMNS_SQL = """
    dedup_key, source, merged_sources, title, company, location,
    contract_type, salary_min, salary_max, remote, skills,
    description, url, published_at
"""

FETCH_OFFERS_SQL = f"""
SELECT json_agg(row_to_json(t)) FROM (
    SELECT {OFFER_COLUMNS_SQL}
    FROM job_offers
) t;
"""


def _sql_str(value: str) -> str:
    """Échappe une chaîne pour l'insérer dans une requête SQL (anti-injection basique)."""
    return "'" + value.replace("'", "''") + "'"


def _run_query(sql: str) -> str:
    cmd = [
        "docker-compose", "exec", "-T", "postgres",
        "psql", "-U", "dataswipe", "-d", "dataswipe",
        "-t", "-A",  # tuples only, unaligned : juste le résultat brut
        "-c", sql,
    ]
    result = subprocess.run(cmd, capture_output=True)

    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Échec de la requête PostgreSQL : {stderr_text}")

    return result.stdout.decode("utf-8", errors="replace").strip()


def fetch_offers() -> list[dict]:
    """Récupère toutes les offres de la base, sous forme de liste de dicts."""
    output = _run_query(FETCH_OFFERS_SQL)
    if not output:
        return []

    offers = json.loads(output)
    logger.info("[data_access] %d offres récupérées depuis PostgreSQL", len(offers) if offers else 0)
    return offers or []


def fetch_offer_by_url(url: str) -> dict | None:
    """Récupère une offre précise par son URL (utilisé par le Sprint 3 pour
    cibler l'offre sur laquelle adapter le CV / générer une lettre)."""
    sql = f"""
    SELECT row_to_json(t) FROM (
        SELECT {OFFER_COLUMNS_SQL}
        FROM job_offers
        WHERE url = {_sql_str(url)}
        LIMIT 1
    ) t;
    """
    output = _run_query(sql)
    if not output:
        return None

    return json.loads(output)
