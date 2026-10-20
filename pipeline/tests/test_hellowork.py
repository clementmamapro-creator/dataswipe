"""
Tests unitaires pour hellowork.py — le card_text simulé reprend le format
observé sur une vraie page de résultats HelloWork (voir historique projet) :
titre, ville - département, contrat, salaire, télétravail, temps écoulé.
"""
from pipeline.scrapers.hellowork import HelloWorkScraper, _slugify


def test_slugify():
    assert _slugify("data engineer") == "data-engineer"
    assert _slugify("chef de projet IT") == "chef-de-projet-it"
    assert _slugify("Développeur Web") == "developpeur-web"


def test_to_normalized_schema_mapping():
    scraper = HelloWorkScraper()
    raw_item = {
        "id": "82266658",
        "url": "https://www.hellowork.com/fr-fr/emplois/82266658.html",
        "card_text": (
            "Data Engineer H/F | Klanik | Lyon - 69 | CDI | "
            "40\u202f000 - 50\u202f000 € / an | Télétravail partiel | "
            "Voir l’offre | il y a 4 jours"
        ),
        "description": "Nous recherchons un Data Engineer maîtrisant Python et Spark.",
    }

    offers = scraper.to_normalized_schema([raw_item])

    assert len(offers) == 1
    offer = offers[0]
    assert offer.source == "hellowork"
    assert offer.source_id == "82266658"
    assert offer.title == "Data Engineer H/F"
    assert offer.company == "Klanik"
    assert offer.location == "Lyon - 69"
    assert offer.contract_type == "CDI"
    assert offer.salary_min == 40000
    assert offer.remote == "Télétravail partiel"
    assert offer.url == "https://www.hellowork.com/fr-fr/emplois/82266658.html"
    assert offer.description == "Nous recherchons un Data Engineer maîtrisant Python et Spark."


def test_to_normalized_schema_handles_suivi_candidature_and_anonymous_company():
    """Régression : certaines cartes commencent par 'Suivi de candidature' et
    l'entreprise peut être anonyme ('Cette entreprise souhaite rester
    anonyme') — ces deux fragments décalaient tout le parsing d'un cran."""
    scraper = HelloWorkScraper()
    raw_item = {
        "id": "77008881",
        "url": "https://www.hellowork.com/fr-fr/emplois/77008881.html",
        "card_text": (
            "Suivi de candidature | Data Engineer H/F | "
            "Cette entreprise souhaite rester anonyme | Lyon - 69 | CDI | "
            "45\u202f000 - 60\u202f000 € / an | Voir l’offre | il y a 15 heures"
        ),
    }

    offers = scraper.to_normalized_schema([raw_item])

    assert len(offers) == 1
    offer = offers[0]
    assert offer.title == "Data Engineer H/F"
    assert offer.company is None
    assert offer.location == "Lyon - 69"
    assert offer.contract_type == "CDI"
    assert offer.salary_min == 45000
