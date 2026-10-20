"""
match_cv.py

Point d'entrée du Sprint 2 : prend un CV (PDF/Word), en extrait les
compétences, les compare à toutes les offres en base, et retourne les
meilleures correspondances triées par score décroissant.

Usage :
    python -m pipeline.matching.match_cv --cv chemin/vers/cv.pdf --top 20
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

from .cv_parser import parse_cv
from .data_access import fetch_offers
from .extract_skills import extract_skills, get_offer_skills
from .scoring import MatchResult, compute_match_score

logger = logging.getLogger("dataswipe.matching.match_cv")


@dataclass
class ScoredOffer:
    offer: dict
    match: MatchResult


def match_cv_to_offers(cv_skills: list[str], offers: list[dict]) -> list[ScoredOffer]:
    """Calcule le score de chaque offre par rapport aux compétences du CV,
    trie par score décroissant, puis par nombre de compétences en commun
    décroissant (un 100% sur 4 compétences est plus fiable/pertinent qu'un
    100% sur une seule compétence isolée)."""
    scored = []
    for offer in offers:
        offer_skills = get_offer_skills(offer)
        match = compute_match_score(cv_skills, offer_skills)
        scored.append(ScoredOffer(offer=offer, match=match))

    scored.sort(key=lambda s: (s.match.score, len(s.match.matched_skills)), reverse=True)
    return scored


def run_matching(cv_path: str, top_n: int = 20) -> list[ScoredOffer]:
    cv_text = parse_cv(cv_path)
    cv_skills = extract_skills(cv_text)

    if not cv_skills:
        logger.warning(
            "[match_cv] Aucune compétence de la taxonomie détectée dans ce CV — "
            "les scores seront tous à 0. Vérifiez que le CV contient bien des "
            "mentions explicites de compétences techniques."
        )

    offers = fetch_offers()
    scored = match_cv_to_offers(cv_skills, offers)

    return scored[:top_n], cv_skills


if __name__ == "__main__":
    import sys
    # Windows/PowerShell utilise cp1252 par défaut, qui ne supporte pas tous
    # les caractères accentués (ex: "é" dans certains noms d'entreprise) —
    # on force l'UTF-8 pour un affichage correct.
    sys.stdout.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Matching CV / offres DataSwipe")
    parser.add_argument("--cv", required=True, help="Chemin vers le CV (PDF ou DOCX)")
    parser.add_argument("--top", type=int, default=20, help="Nombre d'offres à afficher")
    args = parser.parse_args()

    top_offers, cv_skills = run_matching(args.cv, args.top)

    print(f"\n{'=' * 70}")
    print(f"COMPÉTENCES DÉTECTÉES DANS LE CV ({len(cv_skills)})")
    print(f"{'=' * 70}")
    print(", ".join(cv_skills) if cv_skills else "(aucune)")

    print(f"\n{'=' * 70}")
    print(f"TOP {len(top_offers)} OFFRES PAR COMPATIBILITÉ")
    print(f"{'=' * 70}")

    for i, scored in enumerate(top_offers, 1):
        offer = scored.offer
        match = scored.match
        total_offer_skills = len(match.matched_skills) + len(match.missing_skills)
        print(f"\n{i}. [{match.score}% — {len(match.matched_skills)}/{total_offer_skills} compétences] {offer.get('title')} — {offer.get('company') or 'N/A'}")
        print(f"   Localisation : {offer.get('location') or 'N/A'} | Source(s) : {', '.join(offer.get('merged_sources') or [])}")
        if match.matched_skills:
            print(f"   ✓ Compétences en commun : {', '.join(match.matched_skills)}")
        if match.missing_skills:
            print(f"   ✗ Compétences manquantes : {', '.join(match.missing_skills)}")
        if offer.get("url"):
            print(f"   {offer['url']}")
