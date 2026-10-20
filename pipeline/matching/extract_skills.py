"""
extract_skills.py

Détecte les compétences de la taxonomie DataSwipe dans un texte libre
(CV ou description d'offre). Recherche par mots entiers (pas de faux positif
type "R" qui matcherait dans "Recherche"), insensible à la casse, gère les
compétences multi-mots ("Power BI", "Machine Learning"...).
"""

from __future__ import annotations

import re

from .skills_taxonomy import ALL_SKILLS, SKILL_ALIASES

# Compile une regex par compétence (et par alias), avec limites de mots.
# Pour les compétences contenant des caractères spéciaux (C++, C#, CI/CD),
# on échappe le texte puis on autorise les frontières adaptées.
def _build_pattern(term: str) -> re.Pattern:
    escaped = re.escape(term)
    # \b ne fonctionne pas bien autour de "++", "#", "/" — on utilise des
    # frontières plus permissives (espace, début/fin de chaîne, ponctuation)
    return re.compile(rf"(?<![\w+#/]){escaped}(?![\w+#/])", re.IGNORECASE)


_SKILL_PATTERNS: dict[str, re.Pattern] = {skill: _build_pattern(skill) for skill in ALL_SKILLS}
_ALIAS_PATTERNS: dict[str, re.Pattern] = {alias: _build_pattern(alias) for alias in SKILL_ALIASES}


def extract_skills(text: str | None) -> list[str]:
    """Retourne la liste triée (sans doublons) des compétences détectées
    dans `text`, sous leur forme canonique de la taxonomie."""
    if not text:
        return []

    found: set[str] = set()

    for skill, pattern in _SKILL_PATTERNS.items():
        if pattern.search(text):
            found.add(skill)

    for alias, pattern in _ALIAS_PATTERNS.items():
        if pattern.search(text):
            found.add(SKILL_ALIASES[alias])

    return sorted(found)


def get_offer_skills(offer: dict) -> list[str]:
    """
    Compétences d'une offre : utilise le champ `skills` déjà en base s'il
    n'est pas vide (cas WTTJ), sinon extrait depuis le titre + la
    description (cas France Travail, HelloWork qui n'ont pas de champ
    skills fiable/rempli).
    """
    existing = offer.get("skills") or []
    if existing:
        # Les skills WTTJ sont des secteurs ("Big Data", "IT / Digital"...),
        # pas forcément des compétences techniques — on les combine avec
        # l'extraction texte plutôt que de s'y fier seules.
        text_skills = extract_skills(
            f"{offer.get('title', '')} {offer.get('description', '')}"
        )
        return sorted(set(existing) | set(text_skills))

    text = f"{offer.get('title', '')} {offer.get('description', '')}"
    return extract_skills(text)
