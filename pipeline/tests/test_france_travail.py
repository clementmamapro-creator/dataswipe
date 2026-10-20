"""
Tests unitaires pour france_travail.py — pas d'appel réseau ici,
seulement la logique de mapping et la gestion des identifiants manquants.
"""
import os
import pytest
from pipeline.scrapers.france_travail import FranceTravailScraper


def test_raises_without_credentials(monkeypatch):
    monkeypatch.delenv("FRANCE_TRAVAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("FRANCE_TRAVAIL_CLIENT_SECRET", raising=False)
    with pytest.raises(ValueError):
        FranceTravailScraper()


def test_keywords_accepts_string_or_list():
    scraper_str = FranceTravailScraper(client_id="fake_id", client_secret="fake_secret", keywords="data")
    assert scraper_str.keywords == ["data"]

    scraper_list = FranceTravailScraper(client_id="fake_id", client_secret="fake_secret", keywords=["data engineer", "data analyst"])
    assert scraper_list.keywords == ["data engineer", "data analyst"]


def test_to_normalized_schema_mapping():
    scraper = FranceTravailScraper(client_id="fake_id", client_secret="fake_secret")
    raw_item = {
        "id": "123ABC",
        "intitule": "Data Engineer H/F",
        "entreprise": {"nom": "Acme Corp"},
        "lieuTravail": {"libelle": "Paris (75)"},
        "typeContrat": "CDI",
        "salaire": {"libelle": "Selon profil"},
        "competences": [{"libelle": "Python"}, {"libelle": "Airflow"}],
        "description": "Poste de data engineer...",
        "origineOffre": {"urlOrigine": "https://example.com/offre/123"},
        "dateCreation": "2026-08-01T00:00:00Z",
        "teletravail": True,
    }

    offers = scraper.to_normalized_schema([raw_item])

    assert len(offers) == 1
    offer = offers[0]
    assert offer.source == "france_travail"
    assert offer.source_id == "123ABC"
    assert offer.title == "Data Engineer H/F"
    assert offer.company == "Acme Corp"
    assert offer.location == "Paris (75)"
    assert offer.contract_type == "CDI"
    assert "Python" in offer.skills
    assert offer.remote == "hybrid"
