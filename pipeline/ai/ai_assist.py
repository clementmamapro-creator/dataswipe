"""
ai_assist.py

Point d'entrée du Sprint 3 : à partir d'un CV et d'une offre précise (URL),
adapte le CV, génère une lettre de motivation, ou fournit un coaching sur
les compétences manquantes.

Usage :
    python -m pipeline.ai.ai_assist --cv cv.pdf --offer-url "https://..." --mode adapt
    python -m pipeline.ai.ai_assist --cv cv.pdf --offer-url "https://..." --mode letter
    python -m pipeline.ai.ai_assist --cv cv.pdf --offer-url "https://..." --mode coaching
"""

from __future__ import annotations

import argparse
import sys

from ..matching.cv_parser import parse_cv
from ..matching.data_access import fetch_offer_by_url
from ..matching.extract_skills import extract_skills, get_offer_skills
from ..matching.scoring import compute_match_score
from .coaching import generate_coaching
from .cover_letter import generate_cover_letter
from .cv_adapter import adapt_cv


def run(cv_path: str, offer_url: str, mode: str) -> str:
    cv_text = parse_cv(cv_path)
    cv_skills = extract_skills(cv_text)

    offer = fetch_offer_by_url(offer_url)
    if offer is None:
        raise ValueError(f"Aucune offre trouvée en base pour l'URL : {offer_url}")

    if mode == "adapt":
        return adapt_cv(cv_text, offer)
    elif mode == "letter":
        return generate_cover_letter(cv_text, offer)
    elif mode == "coaching":
        offer_skills = get_offer_skills(offer)
        match = compute_match_score(cv_skills, offer_skills)
        print(f"Score de compatibilité actuel : {match.score}%", file=sys.stderr)
        return generate_coaching(offer, match.missing_skills)
    else:
        raise ValueError(f"Mode inconnu : {mode} (attendu : adapt, letter, ou coaching)")


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8")

    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Assistant IA DataSwipe (Sprint 3)")
    parser.add_argument("--cv", required=True, help="Chemin vers le CV (PDF ou DOCX)")
    parser.add_argument("--offer-url", required=True, help="URL de l'offre ciblée (doit exister en base)")
    parser.add_argument("--mode", required=True, choices=["adapt", "letter", "coaching"])
    args = parser.parse_args()

    result = run(args.cv, args.offer_url, args.mode)
    print(f"\n{'=' * 70}")
    print(f"RÉSULTAT ({args.mode})")
    print(f"{'=' * 70}\n")
    print(result)