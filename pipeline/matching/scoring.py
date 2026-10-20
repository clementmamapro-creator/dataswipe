"""
scoring.py

Calcule le score de compatibilité entre les compétences d'un candidat et
celles requises par une offre. Score = pourcentage des compétences de
l'offre que le candidat possède (couverture des attentes de l'offre —
pas l'inverse, un candidat peut avoir plus de compétences que demandé
sans que ça baisse son score).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MatchResult:
    score: float                # 0-100
    matched_skills: list[str]   # compétences du candidat qui matchent l'offre
    missing_skills: list[str]   # compétences demandées par l'offre, absentes du CV


def compute_match_score(cv_skills: list[str], offer_skills: list[str]) -> MatchResult:
    """
    Si l'offre n'a aucune compétence détectée (rare mais possible sur des
    descriptions très courtes), le score est None-équivalent : on retourne
    0 avec des listes vides plutôt que de fausser la moyenne à 100%.
    """
    cv_set = set(cv_skills)
    offer_set = set(offer_skills)

    if not offer_set:
        return MatchResult(score=0.0, matched_skills=[], missing_skills=[])

    matched = sorted(cv_set & offer_set)
    missing = sorted(offer_set - cv_set)

    score = round(len(matched) / len(offer_set) * 100, 1)

    return MatchResult(score=score, matched_skills=matched, missing_skills=missing)
