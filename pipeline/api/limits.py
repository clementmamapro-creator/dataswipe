"""
limits.py

Garde-fous de coût pour l'assistant IA (/assist), seul endpoint qui appelle l'API
Anthropic payante. /match, lui, est 100 % local et gratuit.

Réglages par variables d'environnement (valeurs par défaut prudentes) :
  ASSIST_ENABLED       "true" / "false"  — "false" coupe l'assistant (démo publique sans IA)
  ASSIST_MAX_PER_HOUR  appels IA par adresse IP et par heure   (défaut 20)
  ASSIST_DAILY_CAP     appels IA au total par jour (UTC)         (défaut 200)

Et un cache : même CV + même offre + même mode = même réponse, sans nouvel appel payant.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import OrderedDict, defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

ENABLED = os.environ.get("ASSIST_ENABLED", "true").strip().lower() not in ("0", "false", "no", "non")
MAX_PER_HOUR = int(os.environ.get("ASSIST_MAX_PER_HOUR", "20"))
DAILY_CAP = int(os.environ.get("ASSIST_DAILY_CAP", "200"))
MAX_CV_CHARS = 20_000       # un CV de plus de ~20 000 caractères est anormal : on refuse (coût en tokens)
CACHE_SIZE = 300

_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)
_day = {"date": None, "count": 0}
_cache: "OrderedDict[str, Any]" = OrderedDict()


def cache_key(dedup_key: str, mode: str, cv_text: str) -> str:
    digest = hashlib.sha1(cv_text.encode("utf-8", "ignore")).hexdigest()
    return f"{dedup_key}|{mode}|{digest}"


def cache_get(key: str):
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    return None


def cache_put(key: str, value: Any) -> None:
    with _lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_and_count(ip: str) -> None:
    """Appelée avant chaque appel IA réel (jamais sur un résultat en cache).
    Lève une HTTPException 503/429 avec un message clair si une limite est atteinte."""
    if not ENABLED:
        raise HTTPException(status_code=503, detail="L’assistant IA est désactivé sur ce serveur.")
    now = time.time()
    with _lock:
        if _day["date"] != _today():
            _day.update(date=_today(), count=0)
        if _day["count"] >= DAILY_CAP:
            raise HTTPException(status_code=429, detail="Limite quotidienne de l’assistant IA atteinte. Réessayez demain.")
        window = _hits[ip]
        while window and now - window[0] > 3600:
            window.popleft()
        if len(window) >= MAX_PER_HOUR:
            raise HTTPException(status_code=429, detail=f"Trop de demandes : {MAX_PER_HOUR} par heure maximum. Réessayez plus tard.")
        window.append(now)
        _day["count"] += 1


def snapshot() -> dict:
    with _lock:
        if _day["date"] != _today():
            _day.update(date=_today(), count=0)
        return {"enabled": ENABLED, "remaining_today": max(0, DAILY_CAP - _day["count"])}