"""
security.py

Durcissement de l'API DataSwipe, activé par variables d'environnement :

  ACCESS_CODE   code d'accès exigé (en-tête X-Access-Code) sur /match, /search,
                /assist et /export. Vide : pas de code (développement local).
  CORS_ORIGINS  origines autorisées, séparées par des virgules. Par défaut,
                uniquement l'application servie par l'API elle-même.

S'y ajoutent : limitation des essais de code erroné (par IP) et en-têtes de
sécurité HTTP sur toutes les réponses. Aucune dépendance en plus de FastAPI.
"""

from __future__ import annotations

import hmac
import os
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

PROTECTED = ("/match", "/search", "/assist", "/export")
MAX_FAILURES = 10          # essais erronés tolérés ...
WINDOW_SECONDS = 600       # ... par adresse IP, sur 10 minutes

_failures: dict[str, deque] = defaultdict(deque)


def access_code() -> str:
    return os.getenv("ACCESS_CODE", "").strip()


def allowed_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
    return [o.strip() for o in raw.split(",") if o.strip()]


def _blocked(ip: str, now: float) -> bool:
    q = _failures[ip]
    while q and now - q[0] > WINDOW_SECONDS:
        q.popleft()
    return len(q) >= MAX_FAILURES


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if request.method != "OPTIONS" and path.startswith(PROTECTED) and access_code():
            ip = request.client.host if request.client else "inconnu"
            now = time.time()
            if _blocked(ip, now):
                return JSONResponse({"detail": "Trop d'essais. Réessayez dans quelques minutes."}, status_code=429)
            given = request.headers.get("x-access-code", "")
            if not hmac.compare_digest(given.encode(), access_code().encode()):
                _failures[ip].append(now)
                return JSONResponse({"detail": "Code d'accès requis ou incorrect."}, status_code=401)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if path.startswith(PROTECTED):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    # ajouté en dernier = couche externe : les réponses 401/429 portent aussi les en-têtes CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Access-Code"],
    )
