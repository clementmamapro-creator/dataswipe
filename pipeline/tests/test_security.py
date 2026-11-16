"""Tests du durcissement (security.py) sur une mini-application : aucune base ni API payante."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline.api import security


@pytest.fixture
def client(monkeypatch):
    security._failures.clear()
    monkeypatch.setenv("ACCESS_CODE", "secret-123")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/assist")
    def assist():
        return {"ok": True}

    security.install(app)
    return TestClient(app)


def test_health_reste_public(client):
    assert client.get("/health").status_code == 200


def test_sans_code_refuse(client):
    assert client.post("/assist").status_code == 401


def test_mauvais_code_refuse(client):
    assert client.post("/assist", headers={"X-Access-Code": "faux"}).status_code == 401


def test_bon_code_accepte(client):
    r = client.post("/assist", headers={"X-Access-Code": "secret-123"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"


def test_blocage_apres_trop_essais(client):
    for _ in range(security.MAX_FAILURES):
        client.post("/assist", headers={"X-Access-Code": "faux"})
    assert client.post("/assist", headers={"X-Access-Code": "secret-123"}).status_code == 429


def test_sans_variable_pas_de_code(monkeypatch):
    monkeypatch.delenv("ACCESS_CODE", raising=False)
    app = FastAPI()

    @app.post("/assist")
    def assist():
        return {"ok": True}

    security.install(app)
    assert TestClient(app).post("/assist").status_code == 200


def test_entetes_et_cors_restreint(client):
    r = client.get("/health", headers={"Origin": "http://evil.example"})
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "access-control-allow-origin" not in r.headers
    ok = client.get("/health", headers={"Origin": "http://localhost:8000"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:8000"
