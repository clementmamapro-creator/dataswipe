"""
db.py

Accès PostgreSQL pour l'API. Contrairement aux scripts locaux (Windows),
l'API tourne dans un conteneur Linux — psycopg2-binary s'installe donc sans
problème (wheels précompilées disponibles), pas besoin de contourner via
`docker-compose exec psql` comme pour load.py/data_access.py.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

DSN = os.environ.get(
    "DATASWIPE_POSTGRES_DSN",
    "host=postgres dbname=dataswipe user=dataswipe password=changeme",
)

OFFER_COLUMNS = """
    dedup_key, source, merged_sources, title, company, location,
    contract_type, salary_min, salary_max, remote, skills,
    description, url, published_at
"""


@contextmanager
def get_connection():
    conn = psycopg2.connect(DSN)
    try:
        yield conn
    finally:
        conn.close()


def fetch_offers() -> list[dict]:
    """Récupère toutes les offres (utilisé par /match)."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SELECT {OFFER_COLUMNS} FROM job_offers;")
            return [dict(row) for row in cur.fetchall()]


def fetch_offer_by_dedup_key(dedup_key: str) -> dict | None:
    """Récupère une offre précise (utilisé par /assist)."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"SELECT {OFFER_COLUMNS} FROM job_offers WHERE dedup_key = %s LIMIT 1;",
                (dedup_key,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
