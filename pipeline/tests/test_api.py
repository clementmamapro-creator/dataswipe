"""
Tests pour pipeline/api/main.py — la base PostgreSQL est simulée
(monkeypatch de db.fetch_offers / fetch_offer_by_dedup_key), pas besoin
d'une vraie connexion pour ces tests. Les appels réels à Claude (coaching,
letter, adapt) sont vérifiés manuellement, pas ici.
"""
from fastapi.testclient import TestClient

from pipeline.api import db, main

client = TestClient(main.app)

SAMPLE_OFFER = {
    "dedup_key": "key123",
    "source": "hellowork",
    "merged_sources": ["hellowork"],
    "title": "Data Engineer H/F",
    "company": "Acme",
    "location": "Paris",
    "contract_type": "CDI",
    "salary_min": 45000,
    "salary_max": None,
    "remote": None,
    "skills": [],
    "description": "Nous recherchons un Data Engineer maîtrisant Python et SQL.",
    "url": "https://example.com/offre/123",
    "published_at": None,
}


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_assist_returns_404_for_unknown_offer(monkeypatch):
    monkeypatch.setattr(db, "fetch_offer_by_dedup_key", lambda key: None)
    response = client.post("/assist", json={
        "dedup_key": "inconnu",
        "cv_text": "CV de test",
        "mode": "coaching",
    })
    assert response.status_code == 404


def test_assist_rejects_invalid_mode(monkeypatch):
    monkeypatch.setattr(db, "fetch_offer_by_dedup_key", lambda key: SAMPLE_OFFER)
    response = client.post("/assist", json={
        "dedup_key": "key123",
        "cv_text": "CV de test",
        "mode": "mode_invalide",
    })
    assert response.status_code == 400


def test_match_rejects_unsupported_file_format():
    response = client.post(
        "/match",
        files={"cv_file": ("cv.txt", b"contenu", "text/plain")},
    )
    assert response.status_code == 400
