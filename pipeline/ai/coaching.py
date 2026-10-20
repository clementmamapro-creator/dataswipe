"""
coaching.py

Quand le score de compatibilité est insuffisant, explique précisément
l'écart de compétences et propose des pistes concrètes pour le combler —
plutôt qu'un simple pourcentage decourageant sans plan d'action.
"""

from __future__ import annotations

from .claude_client import call_claude

SYSTEM_PROMPT = """Tu es un coach carrière spécialisé dans les métiers de la
data.

Le candidat vise une offre précise mais n'a pas encore certaines compétences
demandées. Pour chaque compétence manquante, donne :
- Une ressource concrète et gratuite ou peu coûteuse pour l'acquérir
  (nom de plateforme/cours/documentation officielle — pas besoin d'URL exacte)
- Une estimation réaliste du temps nécessaire pour un niveau opérationnel de base

Sois concret et encourageant, jamais générique ("entraîne-toi régulièrement"
ne veut rien dire). Priorise les compétences par ordre d'impact pour ce poste
précis. Réponds en français, sous forme de liste à puces, en terminant par
une phrase d'encouragement courte et sincère (pas de superlatifs creux)."""


def build_prompt(offer: dict, missing_skills: list[str]) -> str:
    skills_list = ", ".join(missing_skills)
    return f"""Offre visée :
Titre : {offer.get('title', 'Non précisé')}
Entreprise : {offer.get('company') or 'Non précisé'}
Description :
{offer.get('description') or offer.get('title', '')}

---

Compétences demandées par cette offre que le candidat n'a pas encore :
{skills_list}
"""


def generate_coaching(offer: dict, missing_skills: list[str]) -> str:
    if not missing_skills:
        return "Aucune compétence manquante détectée pour cette offre — le profil correspond déjà bien."

    prompt = build_prompt(offer, missing_skills)
    return call_claude(SYSTEM_PROMPT, prompt, max_tokens=1200)
