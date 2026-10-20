"""Appel unique à l'API Anthropic (modèle configurable par ASSIST_MODEL)."""
from __future__ import annotations

import os


def complete(system: str, user: str, max_tokens: int = 2500, temperature: float = 0.3) -> str:
    import anthropic

    client = anthropic.Anthropic()  # lit ANTHROPIC_API_KEY
    msg = client.messages.create(
        model=os.getenv("ASSIST_MODEL", "claude-sonnet-5-5"),
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
