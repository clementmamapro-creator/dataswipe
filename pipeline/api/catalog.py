"""
catalog.py

Catalogue d'offres en mémoire : chaque offre est associée à ses compétences,
calculées UNE SEULE FOIS (et non à chaque /match).

Pourquoi : extraire les compétences de ~7 000 descriptions prend plusieurs dizaines
de secondes. Avant, ce travail était refait à chaque dépôt de CV. Désormais :
  - le catalogue est construit au démarrage de l'API, en arrière-plan ;
  - il est reconstruit en arrière-plan toutes les CATALOG_TTL_SECONDS (le pipeline
    Airflow ajoute de nouvelles offres chaque nuit) ; pendant ce temps, l'ancienne
    version continue d'être servie (aucune attente pour l'utilisateur).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from typing import Any

from ..matching.extract_skills import get_offer_skills
from . import db
from .ranking import Index

log = logging.getLogger("uvicorn.error")

CATALOG_TTL_SECONDS = int(os.environ.get("CATALOG_TTL_SECONDS", "1800"))  # 30 min

_lock = threading.Lock()
_state: dict[str, Any] = {"data": None, "index": None, "built_at": 0.0, "building": False, "build_seconds": None}


# Cache des compétences par offre : dedup_key -> (empreinte du contenu, compétences).
# Extraire les compétences coûte ~20 ms par offre (≈ 140 s pour 6 700 offres) : on ne
# recalcule donc que les offres NOUVELLES ou MODIFIÉES. Une reconstruction ordinaire
# (quelques nouvelles offres par nuit) ne prend plus que quelques secondes.
# Ce dictionnaire n'est touché que par le thread de construction (un seul à la fois).
_skills_cache: dict[str, tuple[int, Any]] = {}


_COLUMNS = ("dedup_key, source, title, company, location, contract_type, salary_min, salary_max, remote, "
            "skills, description, url, published_at, collected_at, inserted_at")


def _fetch_rows() -> list[dict]:
    """Lit les offres AVEC leurs métadonnées (contrat, salaire, télétravail, dates) pour les
    filtres. Si la lecture directe échoue, on retombe sur db.fetch_offers (sans filtres)."""
    try:
        import psycopg2
        import psycopg2.extras

        dsn = os.environ.get("DATASWIPE_POSTGRES_DSN")
        if not dsn:
            raise RuntimeError("DATASWIPE_POSTGRES_DSN absent")
        with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM job_offers")
            return [dict(r) for r in cur.fetchall()]
    except Exception:  # noqa: BLE001
        log.exception("[catalog] lecture avec métadonnées impossible, repli sur db.fetch_offers (filtres indisponibles)")
        return db.fetch_offers()


# Le cache est aussi écrit sur disque (dossier ./pipeline, monté depuis le PC) : après un
# redémarrage du conteneur, le catalogue est prêt en quelques secondes au lieu de 2 à 6 minutes.
CACHE_PATH = os.environ.get("SKILLS_CACHE_PATH", os.path.join(os.path.dirname(__file__), ".skills_cache.json"))


def _signature(offer: dict) -> str:
    # md5 (et non hash()) : hash() change à chaque démarrage de Python, md5 reste stable
    raw = f"{offer.get('title')}\x1f{offer.get('description')}".encode("utf-8", "ignore")
    return hashlib.md5(raw).hexdigest()


def _load_disk_cache() -> None:
    global _skills_cache
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        _skills_cache = {k: (v[0], v[1]) for k, v in raw.items()}
        log.info("[catalog] cache disque chargé : %d offres", len(_skills_cache))
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001 - un cache illisible est simplement ignoré
        log.exception("[catalog] cache disque illisible, ignoré")


def _save_disk_cache() -> None:
    try:
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({k: [sig, list(sk)] for k, (sig, sk) in _skills_cache.items()}, f, ensure_ascii=False)
        os.replace(tmp, CACHE_PATH)
    except Exception:  # noqa: BLE001 - l'écriture du cache n'est jamais bloquante
        log.exception("[catalog] écriture du cache disque impossible")


def _build() -> None:
    global _skills_cache
    t0 = time.perf_counter()
    try:
        offers = _fetch_rows()
        t1 = time.perf_counter()
        fresh: dict[str, tuple[int, Any]] = {}
        data, computed = [], 0
        for offer in offers:
            key, sig = offer.get("dedup_key"), _signature(offer)
            hit = _skills_cache.get(key)
            if hit is not None and hit[0] == sig:
                skills = hit[1]
            else:
                skills = get_offer_skills(offer)
                computed += 1
            if key is not None:
                fresh[key] = (sig, skills)
            data.append((offer, skills))
        _skills_cache = fresh                      # les offres purgées disparaissent du cache
        t2 = time.perf_counter()
        index = Index(data)                         # idf, villes, dates, facettes
        t3 = time.perf_counter()
        with _lock:
            _state.update(data=data, index=index, built_at=time.time(), build_seconds=round(t3 - t0, 1))
        log.info("[catalog] %d offres | lecture base %.1fs | compétences %.1fs (%d recalculées, %d en cache) | index %.1fs",
                 len(data), t1 - t0, t2 - t1, computed, len(data) - computed, t3 - t2)
        if computed:
            _save_disk_cache()
    except Exception:  # noqa: BLE001 - on garde l'ancien catalogue si la reconstruction échoue
        log.exception("[catalog] construction impossible")
    finally:
        with _lock:
            _state["building"] = False


def _start_build() -> None:
    with _lock:
        if _state["building"]:
            return
        _state["building"] = True
    threading.Thread(target=_build, daemon=True, name="catalog-build").start()


def warm_up() -> None:
    """À appeler au démarrage de l'API."""
    _load_disk_cache()
    _start_build()


def get_catalog() -> list[tuple[dict, Any]]:
    """Retourne [(offre, compétences_de_l_offre), ...]. Si le catalogue n'est pas
    encore prêt (tout premier démarrage), attend la fin de sa construction."""
    while True:
        with _lock:
            data, age = _state["data"], time.time() - _state["built_at"]
            building = _state["building"]
        if data is not None:
            if age > CATALOG_TTL_SECONDS and not building:
                _start_build()  # rafraîchissement en arrière-plan, on sert l'existant
            return data
        if not building:
            _start_build()
        time.sleep(0.5)


def get_index() -> Index:
    """Index de recherche (offres + compétences + métadonnées + facettes)."""
    get_catalog()                                   # attend/déclenche la construction si besoin
    with _lock:
        return _state["index"]


def status() -> dict:
    with _lock:
        data = _state["data"]
        return {
            "ready": data is not None,
            "offers": len(data) if data is not None else 0,
            "age_seconds": int(time.time() - _state["built_at"]) if data is not None else None,
            "building": _state["building"],
            "build_seconds": _state["build_seconds"],
        }