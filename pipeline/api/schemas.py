"""
schemas.py

Modèles Pydantic pour les requêtes/réponses de l'API. Séparés de main.py
pour rester lisibles à mesure que l'API grossit dans les sprints suivants.
"""

from __future__ import annotations

from pydantic import BaseModel


class OfferMatch(BaseModel):
    dedup_key: str
    source: str
    title: str
    company: str | None
    location: str | None
    url: str | None
    score: float
    matched_skills: list[str]
    missing_skills: list[str]


class MatchResponse(BaseModel):
    cv_skills: list[str]
    total_offers_analyzed: int
    results: list[OfferMatch]


class AssistRequest(BaseModel):
    dedup_key: str
    cv_text: str
    mode: str  # "coaching" | "letter" | "adapt"


class AssistResponse(BaseModel):
    mode: str
    result: str
    score: float | None = None
