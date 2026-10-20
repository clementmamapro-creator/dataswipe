"""
claude_client.py

Wrapper minimal autour du SDK Anthropic. Centralise le choix du modèle et la
gestion de la clé API, pour que les modules cv_adapter/cover_letter/coaching
n'aient qu'à se soucier du contenu des prompts.

Nécessite ANTHROPIC_API_KEY dans .env (voir console.anthropic.com).
"""

from __future__ import annotations

import os

# Haiku : rapide et économique, largement suffisant pour ces tâches de
# rédaction/reformulation — pas besoin de la puissance (ni du coût) d'un
# modèle plus gros pour adapter un CV ou écrire une lettre de motivation.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 2000


def get_client():
    import anthropic  # import local : uniquement nécessaire si Sprint 3 utilisé

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY manquant dans .env — créez une clé sur "
            "console.anthropic.com et ajoutez-la à votre fichier .env."
        )
    return anthropic.Anthropic(api_key=api_key)


def call_claude(system: str, user_message: str, max_tokens: int = DEFAULT_MAX_TOKENS, model: str = DEFAULT_MODEL) -> str:
    """Appelle Claude avec un prompt système + message utilisateur, retourne
    le texte de la réponse."""
    client = get_client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text
