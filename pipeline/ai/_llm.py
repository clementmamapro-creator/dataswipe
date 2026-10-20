"""Appel à l'API Anthropic. Modèle : ASSIST_MODEL (défaut claude-sonnet-5-5), avec repli automatique
sur ASSIST_FALLBACK_MODEL (défaut claude-haiku-4-5) si le modèle principal est refusé.

Une réponse coupée (limite de longueur atteinte) n'est JAMAIS renvoyée telle quelle : on réessaie avec une limite
plus large, et on échoue clairement plutôt que de livrer un CV ou une lettre tronqués."""
from __future__ import annotations

import logging
import os

log = logging.getLogger("uvicorn.error")


def complete(system: str, user: str, max_tokens: int = 2500, temperature: float = 0.3) -> str:
    import anthropic

    client = anthropic.Anthropic()  # lit ANTHROPIC_API_KEY
    main = (os.getenv("ASSIST_MODEL") or "claude-sonnet-5-5").strip()
    fallback = (os.getenv("ASSIST_FALLBACK_MODEL") or "claude-haiku-4-5").strip()
    # Variantes de paramètres, de la plus complète à la plus simple : selon le modèle, la réflexion étendue
    # (qui consomme le budget de sortie) ou le paramètre temperature peuvent être refusés ou activés par défaut.
    variants = [
        {"temperature": temperature, "thinking": {"type": "disabled"}},
        {"thinking": {"type": "disabled"}},
        {"temperature": temperature},
        {},
    ]
    last: Exception | None = None
    for model in dict.fromkeys([main, fallback]):
        for extra in variants:
            budget = max_tokens
            for _attempt in range(2):          # 2e essai avec une limite doublée si la réponse est coupée
                try:
                    msg = client.messages.create(model=model, max_tokens=budget, system=system,
                                                 messages=[{"role": "user", "content": user}], **extra)
                except (anthropic.NotFoundError, anthropic.BadRequestError, anthropic.PermissionDeniedError) as e:
                    last = e
                    log.warning("[assist] %s refusé (%s) : %s", model, sorted(extra), str(e)[:300])
                    break
                text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
                if msg.stop_reason == "max_tokens":
                    log.warning("[assist] réponse coupée à %s jetons (%s) — nouvel essai", budget, model)
                    budget *= 2
                    last = RuntimeError("réponse trop longue, coupée par la limite de longueur")
                    continue
                if model != main:
                    log.warning("[assist] modèle de repli utilisé : %s", model)
                return text
            else:
                continue                        # deux essais coupés avec ce jeu de paramètres : on tente le suivant
    raise last  # type: ignore[misc]