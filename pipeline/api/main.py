"""
main.py

API FastAPI exposant le matching CV/offres et l'assistance IA (coaching,
lettre de motivation, adaptation CV) construits aux Sprints 2 et 3, ainsi que
l'interface web responsive (pipeline/api/static/) servie sur /app/.

Lancement (dans le conteneur Docker) :
    uvicorn pipeline.api.main:app --host 0.0.0.0 --port 8000

Interface web                          : http://localhost:8000/
Documentation interactive auto-générée : http://localhost:8000/docs

Coût : seul /assist appelle l'API Anthropic (payante). /match et /export sont
locaux et gratuits. /assist est protégé par un cache et des limites (voir limits.py).
"""

from __future__ import annotations

import logging
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..ai.coaching import generate_coaching
from ..ai.cover_letter import generate_cover_letter
from ..ai.cv_adapter import adapt_cv
from ..matching.cv_parser import parse_cv
from ..matching.extract_skills import extract_skills, get_offer_skills
from ..matching.scoring import compute_match_score
from ..matching.skills_taxonomy import SKILLS_TAXONOMY
from . import catalog, db, export, limits, ranking
from .schemas import AssistRequest, AssistResponse

log = logging.getLogger("uvicorn.error")

STATIC_DIR = Path(__file__).parent / "static"
MAX_CV_BYTES = 8 * 1024 * 1024
SKILL_CATEGORIES = {skill: category for category, skills in SKILLS_TAXONOMY.items() for skill in skills}

app = FastAPI(title="DataSwipe API", version="0.3.0")

# CORS ouvert en développement — à restreindre avant toute mise en production
# réelle (Sprint 8, sécurité). L'interface web étant servie par cette même API
# (même origine), elle n'en a pas besoin ; il reste utile pour des tests depuis
# un autre site ou une future app native.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _warm_up_catalog() -> None:
    """Construit le catalogue d'offres en arrière-plan : le 1er dépôt de CV est
    alors quasi instantané au lieu de recalculer toutes les compétences."""
    catalog.warm_up()


class OfferHit(BaseModel):
    dedup_key: str
    source: str = ""
    title: str = ""
    company: Optional[str] = None
    location: Optional[str] = None
    url: Optional[str] = None
    score: float                                   # 0-100
    matched_skills: list[str] = []
    missing_skills: list[str] = []
    contract_type: Optional[str] = None
    remote: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    date: Optional[str] = None                     # date de publication, sinon date de première collecte
    date_known: bool = False                       # True : vraie date de publication


class SearchFilters(BaseModel):
    sort: Literal["relevance", "recent", "salary"] = "relevance"
    max_age_days: Optional[int] = Field(default=None, ge=1, le=365)
    city: Optional[str] = Field(default=None, max_length=80)
    contract: Optional[str] = Field(default=None, max_length=80)
    remote: Optional[str] = Field(default=None, max_length=80)
    source: Optional[str] = Field(default=None, max_length=40)
    salary_only: bool = False
    salary_min: Optional[int] = Field(default=None, ge=0, le=1_000_000)
    min_score: float = Field(default=0, ge=0, le=100)
    keyword: Optional[str] = Field(default=None, max_length=80)


class SearchRequest(BaseModel):
    cv_skills: list[str] = Field(max_length=300)
    filters: SearchFilters = SearchFilters()
    offset: int = Field(default=0, ge=0, le=100_000)
    limit: int = Field(default=30, ge=1, le=100)


class SearchResponse(BaseModel):
    total_matching: int
    total_offers: int
    offset: int
    results: list[OfferHit]
    distribution: dict[str, int]
    skill_categories: dict[str, str] = {}


class MatchWithCVResponse(BaseModel):
    """Lecture du CV + première page de résultats + options de filtres. Le texte du CV est
    renvoyé tel quel à /assist ; rien n'est stocké côté serveur."""
    cv_skills: list[str]
    cv_text: str
    skill_categories: dict[str, str] = {}
    total_offers_analyzed: int
    total_matching: int
    results: list[OfferHit]
    distribution: dict[str, int] = {}
    facets: dict = {}


class ExportRequest(BaseModel):
    format: Literal["docx", "pdf"]
    content: str = Field(min_length=1, max_length=40_000)
    filename: str = "document"
    kind: Literal["cv", "letter", ""] = ""            # "cv" ou "letter" : active la mise en page d'en-tête
    photo: Optional[str] = Field(default=None, max_length=4_500_000)   # data URL JPG/PNG, facultative


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "catalog": catalog.status(), "assist": limits.snapshot()}


def _page(cv_skills: list[str], filters: SearchFilters, offset: int, limit: int):
    index = catalog.get_index()
    total, hits, dist = ranking.search(index, cv_skills, filters.model_dump())
    now = datetime.now(timezone.utc)
    page = [OfferHit(**ranking.to_hit(sc, row, m, g, now)) for sc, row, m, g in hits[offset:offset + limit]]
    cats = {s: SKILL_CATEGORIES[s] for s in cv_skills if s in SKILL_CATEGORIES}
    cats |= {s: SKILL_CATEGORIES[s] for h in page for s in h.missing_skills + h.matched_skills if s in SKILL_CATEGORIES}
    return index, total, page, dist, cats


@app.post("/match", response_model=MatchWithCVResponse)
async def match(cv_file: UploadFile = File(...), top: int = 30) -> MatchWithCVResponse:
    """Upload d'un CV (PDF/DOCX) -> compétences + première page d'offres classées.
    100 % local : aucun appel à l'API Anthropic, donc aucun coût."""
    t0 = time.perf_counter()
    top = max(1, min(top, 100))
    suffix = Path(cv_file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".docx"):
        raise HTTPException(status_code=400, detail="Format non supporté (PDF ou DOCX uniquement)")

    content = await cv_file.read()
    if len(content) > MAX_CV_BYTES:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (8 Mo maximum)")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        cv_text = parse_cv(tmp_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    t1 = time.perf_counter()

    cv_skills = list(extract_skills(cv_text))
    t2 = time.perf_counter()
    index, total, page, dist, cats = _page(cv_skills, SearchFilters(), 0, top)
    t3 = time.perf_counter()
    log.info("[match] %d offres | lecture CV %.1fs | compétences CV %.1fs | scoring+tri %.2fs | total %.1fs | répartition %s",
             len(index.rows), t1 - t0, t2 - t1, t3 - t2, t3 - t0, dist)

    return MatchWithCVResponse(
        cv_skills=cv_skills, cv_text=cv_text, skill_categories=cats,
        total_offers_analyzed=len(index.rows), total_matching=total, results=page,
        distribution=dist, facets=index.facets,
    )


@app.post("/search", response_model=SearchResponse)
def search(payload: SearchRequest) -> SearchResponse:
    """Filtre, trie et pagine les offres pour des compétences de CV déjà lues. Local et gratuit."""
    index, total, page, dist, cats = _page(payload.cv_skills, payload.filters, payload.offset, payload.limit)
    return SearchResponse(total_matching=total, total_offers=len(index.rows), offset=payload.offset,
                          results=page, distribution=dist, skill_categories=cats)


class AssistOut(AssistResponse):
    # compétences citées dans le texte généré mais absentes du CV d'origine (à vérifier)
    added_skills: list[str] = []


@app.post("/assist", response_model=AssistOut)
def assist(payload: AssistRequest, request: Request) -> AssistOut:
    """Coaching, lettre de motivation, ou adaptation CV pour une offre précise
    (identifiée par son dedup_key, renvoyé par /match)."""
    if payload.mode not in ("coaching", "letter", "adapt"):
        raise HTTPException(status_code=400, detail="mode invalide (attendu : coaching, letter, ou adapt)")
    if len(payload.cv_text) > limits.MAX_CV_CHARS:
        raise HTTPException(status_code=413, detail="Texte du CV trop long pour l’assistant")

    offer = db.fetch_offer_by_dedup_key(payload.dedup_key)
    if offer is None:
        raise HTTPException(status_code=404, detail="Offre introuvable (dedup_key invalide)")

    key = limits.cache_key(payload.dedup_key, payload.mode, payload.cv_text)
    cached = limits.cache_get(key)
    if cached is not None:
        return cached

    ip = (request.client.host if request.client else "inconnu")

    if payload.mode == "coaching":
        cv_skills = extract_skills(payload.cv_text)
        offer_skills = get_offer_skills(offer)
        m = compute_match_score(cv_skills, offer_skills)
        if m.missing_skills:               # sans compétence manquante, pas d'appel IA à payer
            limits.check_and_count(ip)
        response = AssistResponse(mode="coaching", result=generate_coaching(offer, m.missing_skills), score=m.score)
    else:
        limits.check_and_count(ip)
        if payload.mode == "letter":
            response = AssistResponse(mode="letter", result=generate_cover_letter(payload.cv_text, offer))
        else:
            response = AssistResponse(mode="adapt", result=adapt_cv(payload.cv_text, offer))

    out = AssistOut(**response.model_dump())
    if payload.mode in ("letter", "adapt") and isinstance(response.result, str):
        # Garde-fou local et gratuit : l'IA a-t-elle ajouté des compétences que le CV d'origine ne mentionne pas ?
        added = set(extract_skills(response.result)) - set(extract_skills(payload.cv_text))
        out.added_skills = sorted(added)
    limits.cache_put(key, out)
    return out


@app.post("/export")
def export_document(payload: ExportRequest) -> Response:
    """Convertit un texte (CV adapté, lettre) en fichier Word ou PDF. Local et gratuit."""
    ascii_name = unicodedata.normalize("NFKD", payload.filename).encode("ascii", "ignore").decode()
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in ascii_name).strip("_")[:80] or "document"
    try:
        photo = export.prepare_photo(payload.photo) if payload.photo else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        if payload.format == "docx":
            data = export.to_docx(payload.content, safe, payload.kind, photo)
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            data = export.to_pdf(payload.content, safe, payload.kind, photo)
            media = "application/pdf"
    except ImportError as e:
        raise HTTPException(status_code=501, detail=f"Export indisponible : bibliothèque manquante ({e.name}). "
                                                    "Ajoutez-la à requirements.txt puis reconstruisez l’image.")
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{safe}.{payload.format}"'})


# ---- Interface web (déclarée en dernier : les routes API restent prioritaires) ----
if STATIC_DIR.is_dir():
    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/app/")

    app.mount("/app", StaticFiles(directory=STATIC_DIR, html=True), name="app")