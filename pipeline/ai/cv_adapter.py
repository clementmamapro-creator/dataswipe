"""
cv_adapter.py — CV adapté à une offre, sans invention.
Le niveau d'expérience, le nom et l'en-tête sont calculés par le code (profile.py) et imposés à l'IA.
"""
from __future__ import annotations

import re

from . import _llm, profile

SYSTEM = """Tu es un conseiller en recrutement français expérimenté. Tu adaptes le CV d'un candidat à une offre.

RÈGLES ABSOLUES (leur violation rend le document inutilisable) :
1. FIDÉLITÉ : n'utilise que des faits présents dans le CV d'origine. N'ajoute AUCUNE compétence, technologie, outil,
   certification, diplôme, employeur, mission, chiffre ou durée absents du CV. Si l'offre demande une compétence que le
   candidat n'a pas, ne la mets pas dans le CV (tu peux seulement valoriser une compétence voisine réellement présente).
2. NIVEAU : le niveau du candidat t'est donné dans « FAITS CALCULÉS ». Respecte-le strictement. Ne reprends jamais le
   niveau demandé par l'offre (« Senior », « Confirmé », « 5 ans ») si le candidat ne l'a pas, n'écris jamais « expert »,
   « expertise confirmée » ou un nombre d'années supérieur à celui indiqué. Une alternance compte comme expérience, mais
   se présente comme une alternance.
3. TITRE : l'en-tête (nom + poste visé) est ajouté par le système. Ne l'écris pas. Le poste visé est le titre de l'offre :
   ne le transforme pas en titre que le candidat aurait occupé.
4. FORME : français soigné, orthographe vérifiée, aucun mot inventé. Pas d'emojis. Puces avec « - ».
   Une page et demie maximum. Verbes d'action, résultats seulement s'ils figurent dans le CV.

STRUCTURE (Markdown) :
## Profil — 2 à 3 phrases honnêtes : niveau réel, domaine, ce qui correspond à l'offre.
## Compétences clés — regroupées par catégorie, ordonnées selon l'offre, uniquement celles du CV.
## Expérience professionnelle — ### Poste — Entreprise (dates), puis 3 à 5 puces reformulées pour l'offre.
## Formation — fidèle au CV.
## Langues / Certifications — seulement si présentes dans le CV.
Ne rajoute aucune note ni commentaire hors du CV."""


def _strip_header(text: str) -> str:
    """Retire un éventuel en-tête produit malgré la consigne (titre # ou ligne de poste en gras au tout début)."""
    lines = text.strip().split("\n")
    while lines and (lines[0].startswith("# ") or not lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()


def adapt_cv(cv_text: str, offer) -> str:
    f = profile.facts(cv_text, offer)
    desc = (profile._get(offer, "description", "desc", "snippet") or "")[:6000]
    user = f"""FAITS CALCULÉS (fiables, à respecter) :
- Nom : {f['name'] or 'non détecté'}
- Expérience professionnelle détectée : environ {f['years']} an(s) — {f['wording']}
- Poste visé : {f['target']} chez {f['company'] or 'entreprise non précisée'}

OFFRE :
{desc or f['target']}

CV D'ORIGINE :
{cv_text}

Rédige le CV adapté (sans l'en-tête nom/poste) en respectant toutes les règles."""
    body = _strip_header(_llm.complete(SYSTEM, user, max_tokens=2800, temperature=0.2))
    return profile.cv_header(f, profile.contacts(cv_text)) + "\n" + body