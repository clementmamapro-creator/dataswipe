"""
normalize.py

Étape ETL du Sprint 1 : prend en entrée les offres brutes collectées par les
3 scrapers (via registry.run_all(), déjà au format JobOffer.to_dict()) et
produit une liste finale propre, dédupliquée, prête pour insertion PostgreSQL.

Deux responsabilités :
    1. clean_offer()       — nettoyage champ par champ (espaces, valeurs vides,
                              casse) sur une offre individuelle
    2. deduplicate_offers() — regroupe les offres identiques publiées sur
                              plusieurs sources (ex: même poste sur WTTJ et
                              HelloWork), via une clé normalisée
                              titre + entreprise + ville — pas de comparaison
                              floue (trop coûteuse sur 7000+ offres), mais une
                              égalité exacte après nettoyage agressif du texte.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Optional

logger = logging.getLogger("dataswipe.etl.normalize")

# Suffixes très courants à retirer avant comparaison, pour que
# "Data Engineer H/F" et "Data Engineer (H/F)" soient reconnus identiques.
NOISE_SUFFIXES = re.compile(
    r"\b(h/?f|f/?h|h\s*ou\s*f)\b|\(.*?\)|[-–—]\s*$", re.IGNORECASE
)

# Plage de salaires annuels bruts jugés exploitables (en euros).
# En dehors (stages/alternances, montants mensuels ou journaliers saisis comme
# annuels, erreurs de saisie type 14 600 000), le salaire est considéré comme
# non exploitable et mis à None pour ne pas fausser les statistiques.
SALARY_MIN_VALID = 12_000
SALARY_MAX_VALID = 300_000


def _normalize_text(value: Optional[str]) -> str:
    """Nettoyage agressif pour comparaison : minuscules, sans accents, sans
    ponctuation, espaces multiples réduits. Utilisé UNIQUEMENT pour construire
    la clé de déduplication — jamais pour l'affichage final."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = NOISE_SUFFIXES.sub(" ", value.lower())
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


# Chaque source formate la localisation différemment :
#   France Travail : "Paris (75)"       WTTJ : "Courbevoie"       HelloWork : "Lyon - 69"
# On ne garde que le nom de ville pour permettre le matching inter-sources.
LOCATION_SUFFIX = re.compile(r"\s*[\(\-–—]\s*\d{2,5}\)?\s*$")


def _normalize_location(value: Optional[str]) -> str:
    if not value:
        return ""
    value = LOCATION_SUFFIX.sub("", value)
    return _normalize_text(value)


def _sanitize_salary(offer: dict[str, Any]) -> dict[str, Any]:
    """Met salary_min et salary_max à None si le salaire n'est pas exploitable :
    minimum hors de la plage [SALARY_MIN_VALID, SALARY_MAX_VALID], ou maximum
    renseigné mais inférieur au minimum (incohérence de la source)."""
    lo = offer.get("salary_min")
    hi = offer.get("salary_max")

    hors_plage = lo is not None and not (SALARY_MIN_VALID <= lo <= SALARY_MAX_VALID)
    incoherent = lo is not None and hi is not None and hi > 0 and hi < lo

    if hors_plage or incoherent:
        offer["salary_min"] = None
        offer["salary_max"] = None
    return offer


def clean_offer(offer: dict[str, Any]) -> dict[str, Any]:
    """Nettoie une offre individuelle : trim des chaînes, valeurs vides -> None,
    normalisation légère de la casse (sans dénaturer l'affichage)."""
    cleaned = dict(offer)

    for field in ("title", "company", "location", "contract_type", "description", "url"):
        value = cleaned.get(field)
        if isinstance(value, str):
            value = value.strip()
            cleaned[field] = value if value else None

    # Titre : retire les espaces multiples internes (fréquent chez HelloWork,
    # où plusieurs balises HTML adjacentes laissent parfois un double espace)
    if cleaned.get("title"):
        cleaned["title"] = re.sub(r"\s+", " ", cleaned["title"])

    # Compétences : retire les doublons et les valeurs vides, garde l'ordre
    skills = cleaned.get("skills") or []
    seen = set()
    clean_skills = []
    for s in skills:
        if s and s not in seen:
            seen.add(s)
            clean_skills.append(s)
    cleaned["skills"] = clean_skills

    # Salaire : force en int ou None (au cas où une source renverrait une string)
    for field in ("salary_min", "salary_max"):
        value = cleaned.get(field)
        if value is not None:
            try:
                cleaned[field] = int(value)
            except (ValueError, TypeError):
                cleaned[field] = None

    # Salaire : écarte les valeurs aberrantes ou incohérentes
    cleaned = _sanitize_salary(cleaned)

    return cleaned


def compute_dedup_key(offer: dict[str, Any]) -> str:
    """Clé de déduplication : titre + entreprise + ville (sans département/CP), normalisés."""
    title = _normalize_text(offer.get("title"))
    company = _normalize_text(offer.get("company"))
    location = _normalize_location(offer.get("location"))
    return f"{title}|{company}|{location}"


def deduplicate_offers(offers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """
    Regroupe les offres partageant la même clé de déduplication. Pour chaque
    groupe, conserve l'offre la plus "riche" (description la plus longue) comme
    représentant, et ajoute un champ `merged_sources` listant toutes les
    sources d'origine du groupe.

    Retourne (offres_finales, stats) où stats contient le nombre de doublons
    retirés par ce processus.
    """
    groups: dict[str, list[dict[str, Any]]] = {}

    for offer in offers:
        # Offres sans titre exploitable (cas limite) : jamais fusionnées entre
        # elles, chacune reste distincte (clé unique par source_id)
        key = compute_dedup_key(offer)
        if not key.strip("|"):
            key = f"__unique__{offer.get('source')}_{offer.get('source_id')}"
        groups.setdefault(key, []).append(offer)

    final_offers = []
    duplicates_removed = 0

    for key, group in groups.items():
        if len(group) == 1:
            offer = group[0]
            offer["merged_sources"] = [offer.get("source")]
            offer["dedup_key"] = key
            final_offers.append(offer)
            continue

        # Plusieurs offres pour la même clé : on garde celle avec la
        # description la plus longue comme représentant (généralement la
        # plus complète), et on liste toutes les sources d'origine.
        duplicates_removed += len(group) - 1
        best = max(group, key=lambda o: len(o.get("description") or ""))
        best = dict(best)
        best["merged_sources"] = sorted({o.get("source") for o in group})
        best["dedup_key"] = key
        final_offers.append(best)

    stats = {
        "input_count": len(offers),
        "output_count": len(final_offers),
        "duplicates_removed": duplicates_removed,
    }
    return final_offers, stats


def normalize_offers(offers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Point d'entrée principal de l'ETL : nettoyage puis déduplication."""
    cleaned = [clean_offer(o) for o in offers]
    deduped, stats = deduplicate_offers(cleaned)
    logger.info(
        "[normalize] %d offres en entrée -> %d après dédup (%d doublons retirés)",
        stats["input_count"], stats["output_count"], stats["duplicates_removed"]
    )
    return deduped, stats


if __name__ == "__main__":
    # Test manuel : python -m pipeline.etl.normalize
    # Lance les 3 scrapers puis applique l'ETL, avec un résumé avant/après.
    import logging as _logging
    from collections import Counter

    from dotenv import load_dotenv

    from pipeline.scrapers.registry import run_all

    _logging.basicConfig(level=_logging.INFO)
    load_dotenv()

    raw_offers = run_all()
    print(f"\n{len(raw_offers)} offres brutes collectées")

    final_offers, stats = normalize_offers(raw_offers)

    print(f"\n{'=' * 60}")
    print("RÉSUMÉ ETL")
    print(f"{'=' * 60}")
    print(f"  Offres en entrée      : {stats['input_count']}")
    print(f"  Offres en sortie      : {stats['output_count']}")
    print(f"  Doublons retirés      : {stats['duplicates_removed']}")

    multi_source = [o for o in final_offers if len(o.get("merged_sources", [])) > 1]
    print(f"  Offres multi-sources  : {len(multi_source)}")
    if multi_source:
        print("\n--- Exemple d'offre fusionnée (présente sur plusieurs sources) ---")
        example = multi_source[0]
        print(f"  Titre     : {example['title']}")
        print(f"  Entreprise: {example['company']}")
        print(f"  Sources   : {example['merged_sources']}")

    source_counts = Counter(s for o in final_offers for s in o.get("merged_sources", []))
    print("\n--- Répartition (avant dédup, par source d'origine) ---")
    for source, count in source_counts.items():
        print(f"  {source:20s} : {count}")