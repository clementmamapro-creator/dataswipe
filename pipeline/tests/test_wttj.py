"""
Tests unitaires pour wttj.py — le raw_item ci-dessous est une version allégée
d'une vraie réponse Algolia obtenue en conditions réelles (voir historique projet).
"""
from pipeline.scrapers.wttj import WelcomeToTheJungleScraper


def test_to_normalized_schema_mapping():
    scraper = WelcomeToTheJungleScraper()
    raw_item = {
        "slug": "senior-data-engineer-h-f_paris",
        "name": "Senior Data Engineer (H/F)",
        "profile": "Tu maîtrises Python ou Scala en profondeur...",
        "organization": {"name": "Code Busters", "slug": "code-busters"},
        "sectors": [
            {"name": {"fr": "Logiciels"}},
            {"name": {"fr": "Big Data"}},
        ],
        "contract_type": "FULL_TIME",
        "contract_type_names": {"fr": "CDI"},
        "salary_currency": "EUR",
        "salary_minimum": 55000,
        "salary_maximum": None,
        "salary_yearly_minimum": 55000,
        "office": {"city": "Courbevoie", "country": "France"},
        "remote": "partial",
        "objectID": "4089122",
        "published_at": "2026-08-17T10:00:00.000+02:00",
    }

    offers = scraper.to_normalized_schema([raw_item])

    assert len(offers) == 1
    offer = offers[0]
    assert offer.source == "wttj"
    assert offer.source_id == "4089122"
    assert offer.title == "Senior Data Engineer (H/F)"
    assert offer.company == "Code Busters"
    assert offer.location == "Courbevoie"
    assert offer.contract_type == "CDI"
    assert offer.salary_min == 55000
    assert offer.remote == "partial"
    assert "Big Data" in offer.skills
    assert offer.url == "https://www.welcometothejungle.com/fr/companies/code-busters/jobs/senior-data-engineer-h-f_paris"
