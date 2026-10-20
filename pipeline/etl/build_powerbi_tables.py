"""
build_powerbi_tables.py

Prépare un modèle en étoile pour Power BI, à partir de la table job_offers
existante :
  - dim_skill          : catalogue des compétences de la taxonomie, avec leur
                          catégorie (Langages, Cloud & Infra, BI...)
  - job_offer_skills    : table de liaison (une ligne par compétence détectée
                          par offre) — recalculée ici via la même logique que
                          le matching (extract_skills), car le champ brut
                          `skills` de job_offers est sparse/incohérent selon
                          la source (vide pour France Travail/HelloWork,
                          secteurs pour WTTJ, pas de vraies compétences).
  - job_offer_sources    : table de liaison (une ligne par source d'origine
                          par offre), dépliée depuis merged_sources.

Usage : python -m pipeline.etl.build_powerbi_tables
"""

from __future__ import annotations

import logging

from ..matching.data_access import fetch_offers
from ..matching.extract_skills import get_offer_skills
from ..matching.skills_taxonomy import ALL_SKILLS, SKILLS_TAXONOMY

_ALL_SKILLS_SET = set(ALL_SKILLS)
from .load import _sql_str, run_sql

logger = logging.getLogger("dataswipe.etl.build_powerbi_tables")

BATCH_SIZE = 500

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

TRUNCATE job_offer_skills, job_offer_sources;
"""


def populate_dim_skill() -> None:
    rows = []
    for category, skills in SKILLS_TAXONOMY.items():
        for skill in skills:
            rows.append(f"({_sql_str(skill)}, {_sql_str(category)})")

    values_block = ",\n".join(rows)
    sql = f"""
INSERT INTO dim_skill (skill, category) VALUES
{values_block}
ON CONFLICT (skill) DO UPDATE SET category = EXCLUDED.category;
"""
    result = run_sql(sql)
    if result.returncode != 0:
        raise RuntimeError(f"Échec peuplement dim_skill : {result.stderr}")
    logger.info("[build_powerbi_tables] dim_skill peuplée (%d compétences)", len(rows))


def populate_bridge_tables() -> None:
    offers = fetch_offers()
    logger.info("[build_powerbi_tables] %d offres à traiter", len(offers))

    skill_rows = []
    source_rows = []

    for offer in offers:
        dedup_key = offer.get("dedup_key")
        if not dedup_key:
            continue

        for skill in get_offer_skills(offer):
            if skill in _ALL_SKILLS_SET:
                skill_rows.append((dedup_key, skill))

        for source in (offer.get("merged_sources") or [offer.get("source")]):
            if source:
                source_rows.append((dedup_key, source))

    _insert_batched("job_offer_skills", ["dedup_key", "skill"], skill_rows)
    _insert_batched("job_offer_sources", ["dedup_key", "source"], source_rows)

    logger.info(
        "[build_powerbi_tables] %d lignes compétences, %d lignes sources insérées",
        len(skill_rows), len(source_rows)
    )


def _insert_batched(table: str, columns: list[str], rows: list[tuple]) -> None:
    if not rows:
        return

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        values_clause = ",\n".join(
            "(" + ", ".join(_sql_str(v) for v in row) + ")" for row in batch
        )
        sql = f"""
INSERT INTO {table} ({', '.join(columns)}) VALUES
{values_clause}
ON CONFLICT DO NOTHING;
"""
        result = run_sql(sql)
        if result.returncode != 0:
            raise RuntimeError(f"Échec insertion {table} (lot {i}) : {result.stderr}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("Création des tables...")
    result = run_sql(CREATE_TABLES_SQL)
    if result.returncode != 0:
        raise RuntimeError(f"Échec création des tables : {result.stderr}")

    print("Peuplement de dim_skill...")
    populate_dim_skill()

    print("Peuplement des tables de liaison (peut prendre 1-2 minutes)...")
    populate_bridge_tables()

    print("\nTerminé — tables prêtes pour Power BI : dim_skill, job_offer_skills, job_offer_sources")
