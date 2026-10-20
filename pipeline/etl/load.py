"""
load.py

Dernière étape du Sprint 1 : insère les offres nettoyées/dédupliquées
(sortie de normalize.normalize_offers) dans PostgreSQL.

⚠️ Changement d'approche : pg8000 (driver PostgreSQL 100% Python) souffre
d'un bug d'authentification SCRAM non résolu avec cet environnement
(Python 3.14 très récent — cause exacte non identifiée, `psql` en direct
fonctionne parfaitement avec les mêmes identifiants). Plutôt que de dépendre
d'un driver Python tiers peu fiable ici, on passe par `psql` directement via
`docker-compose exec`, qui a été testé et validé en conditions réelles.

Stratégie d'upsert : chaque offre a un `dedup_key` (voir normalize.py) qui
sert de clé unique en base. Les offres sont envoyées par lots de 300 dans des
requêtes INSERT ... ON CONFLICT DO UPDATE, exécutées via psql.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any

from pipeline.etl.normalize import compute_dedup_key

logger = logging.getLogger("dataswipe.etl.load")

BATCH_SIZE = 300

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS job_offers (
    dedup_key       TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    merged_sources  TEXT[] NOT NULL,
    title           TEXT NOT NULL,
    company         TEXT,
    location        TEXT,
    contract_type   TEXT,
    salary_min      INTEGER,
    salary_max      INTEGER,
    remote          TEXT,
    skills          TEXT[],
    description     TEXT,
    url             TEXT,
    published_at    TEXT,
    collected_at    TIMESTAMPTZ NOT NULL,
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

COLUMNS = [
    "dedup_key", "source", "source_id", "merged_sources", "title", "company",
    "location", "contract_type", "salary_min", "salary_max", "remote",
    "skills", "description", "url", "published_at", "collected_at",
]

UPDATE_SET = ", ".join(
    f"{col} = EXCLUDED.{col}" for col in COLUMNS if col != "dedup_key"
) + ", updated_at = now()"


def _sql_str(value: Any) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _sql_int(value: Any) -> str:
    if value is None:
        return "NULL"
    try:
        return str(int(value))
    except (ValueError, TypeError):
        return "NULL"


def _sql_array(values: list[str] | None) -> str:
    if not values:
        return "ARRAY[]::text[]"
    return "ARRAY[" + ",".join(_sql_str(v) for v in values) + "]::text[]"


def _offer_to_values_row(offer: dict[str, Any]) -> str:
    return "(" + ", ".join([
        _sql_str(offer.get("dedup_key")),
        _sql_str(offer.get("source")),
        _sql_str(offer.get("source_id")),
        _sql_array(offer.get("merged_sources")),
        _sql_str(offer.get("title")),
        _sql_str(offer.get("company")),
        _sql_str(offer.get("location")),
        _sql_str(offer.get("contract_type")),
        _sql_int(offer.get("salary_min")),
        _sql_int(offer.get("salary_max")),
        _sql_str(offer.get("remote")),
        _sql_array(offer.get("skills")),
        _sql_str(offer.get("description")),
        _sql_str(offer.get("url")),
        _sql_str(offer.get("published_at")),
        _sql_str(offer.get("collected_at")),
    ]) + ")"


def run_sql(sql: str) -> subprocess.CompletedProcess:
    """Exécute du SQL via `docker-compose exec -T postgres psql`.

    ⚠️ Encodage forcé en UTF-8 explicitement (encode/decode manuels plutôt que
    text=True) : sur Windows, subprocess utilise par défaut l'encodage de la
    console (cp1252), qui plante sur des caractères comme "→" présents dans
    certaines descriptions d'offres HelloWork/WTTJ.
    """
    cmd = [
        "docker-compose", "exec", "-T", "postgres",
        "psql", "-U", "dataswipe", "-d", "dataswipe",
        "-v", "ON_ERROR_STOP=1", "-f", "-",
    ]
    result = subprocess.run(
        cmd,
        input=sql.encode("utf-8"),
        capture_output=True,
    )
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        logger.error("[load] Échec psql : %s", stderr_text[:1000])
        # On reconstruit un objet avec stderr en str pour rester compatible
        # avec le reste du code qui traite result.stderr comme du texte.
        result.stderr = stderr_text
    else:
        result.stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
    return result


def ensure_table() -> None:
    result = run_sql(CREATE_TABLE_SQL)
    if result.returncode != 0:
        raise RuntimeError(f"Impossible de créer la table job_offers : {result.stderr}")
    logger.info("[load] Table job_offers vérifiée/créée")


def load_offers(offers: list[dict[str, Any]]) -> dict[str, int]:
    """Insère (ou met à jour) une liste d'offres normalisées en base, par lots."""
    ensure_table()

    stats = {"processed": 0, "skipped": 0, "batches_failed": 0}

    # Filet de sécurité : si dedup_key n'a pas été posé par normalize.py
    # (version locale désynchronisée), on le calcule ici plutôt que d'ignorer
    # l'offre silencieusement.
    for offer in offers:
        if not offer.get("dedup_key"):
            offer["dedup_key"] = compute_dedup_key(offer)
        if not offer.get("merged_sources"):
            offer["merged_sources"] = [offer.get("source")]

    valid_offers = [o for o in offers if o.get("title") and o.get("source_id") and o.get("dedup_key")]
    stats["skipped"] = len(offers) - len(valid_offers)

    for i in range(0, len(valid_offers), BATCH_SIZE):
        batch = valid_offers[i:i + BATCH_SIZE]
        values_clause = ",\n".join(_offer_to_values_row(o) for o in batch)

        sql = f"""
INSERT INTO job_offers ({', '.join(COLUMNS)})
VALUES
{values_clause}
ON CONFLICT (dedup_key) DO UPDATE SET {UPDATE_SET};
"""
        result = run_sql(sql)
        if result.returncode != 0:
            stats["batches_failed"] += 1
            logger.error("[load] Lot %d-%d échoué", i, i + len(batch))
        else:
            stats["processed"] += len(batch)
            logger.info("[load] Lot inséré : %d/%d offres traitées", stats["processed"], len(valid_offers))

    logger.info(
        "[load] %d offres insérées/mises à jour, %d ignorées, %d lots en échec",
        stats["processed"], stats["skipped"], stats["batches_failed"]
    )
    return stats


def load_offers_via_psycopg2(offers: list[dict[str, Any]], dsn: str) -> dict[str, int]:
    """
    Variante de load_offers() pour l'exécution DANS le conteneur Airflow
    (Linux) plutôt que depuis Windows. Là-bas, psycopg2-binary s'installe
    normalement (wheels précompilées disponibles sous Linux), donc pas besoin
    de contourner via `docker-compose exec psql` comme sur le poste Windows.

    Réutilise volontairement toute la logique SQL déjà testée (_sql_str,
    _sql_array, _offer_to_values_row, CREATE_TABLE_SQL...) plutôt que de la
    dupliquer — seul le mécanisme d'exécution change.

    `dsn` : chaîne de connexion, ex.
    "host=postgres dbname=dataswipe user=dataswipe password=changeme"
    (host="postgres" = nom du service Docker, pas "localhost", car on est
    dans le même réseau Docker interne).
    """
    import psycopg2  # import local : uniquement nécessaire dans le conteneur Airflow

    stats = {"processed": 0, "skipped": 0, "batches_failed": 0}

    for offer in offers:
        if not offer.get("dedup_key"):
            offer["dedup_key"] = compute_dedup_key(offer)
        if not offer.get("merged_sources"):
            offer["merged_sources"] = [offer.get("source")]

    valid_offers = [o for o in offers if o.get("title") and o.get("source_id") and o.get("dedup_key")]
    stats["skipped"] = len(offers) - len(valid_offers)

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
        conn.commit()
        logger.info("[load] Table job_offers vérifiée/créée (psycopg2)")

        for i in range(0, len(valid_offers), BATCH_SIZE):
            batch = valid_offers[i:i + BATCH_SIZE]
            values_clause = ",\n".join(_offer_to_values_row(o) for o in batch)
            sql = f"""
INSERT INTO job_offers ({', '.join(COLUMNS)})
VALUES
{values_clause}
ON CONFLICT (dedup_key) DO UPDATE SET {UPDATE_SET};
"""
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                conn.commit()
                stats["processed"] += len(batch)
                logger.info("[load] Lot inséré : %d/%d offres traitées", stats["processed"], len(valid_offers))
            except Exception:
                conn.rollback()
                stats["batches_failed"] += 1
                logger.exception("[load] Lot %d-%d échoué", i, i + len(batch))
    finally:
        conn.close()

    logger.info(
        "[load] %d offres insérées/mises à jour, %d ignorées, %d lots en échec",
        stats["processed"], stats["skipped"], stats["batches_failed"]
    )
    return stats


if __name__ == "__main__":
    import logging as _logging

    from dotenv import load_dotenv

    from pipeline.etl.normalize import normalize_offers
    from pipeline.scrapers.registry import run_all

    _logging.basicConfig(level=_logging.INFO)
    load_dotenv()

    raw_offers = run_all()
    print(f"\n{len(raw_offers)} offres brutes collectées")

    final_offers, norm_stats = normalize_offers(raw_offers)
    print(f"{len(final_offers)} offres après normalisation/dédup")

    load_stats = load_offers(final_offers)

    print(f"\n{'=' * 60}")
    print("RÉSUMÉ CHARGEMENT POSTGRESQL")
    print(f"{'=' * 60}")
    print(f"  Offres normalisées    : {len(final_offers)}")
    print(f"  Insérées/mises à jour : {load_stats['processed']}")
    print(f"  Ignorées              : {load_stats['skipped']}")
    print(f"  Lots en échec         : {load_stats['batches_failed']}")

