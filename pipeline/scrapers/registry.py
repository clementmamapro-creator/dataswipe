"""
registry.py

Liste centrale des scrapers actifs. Le DAG Airflow ne connaît jamais
un site en particulier : il boucle sur SCRAPERS.

Pour ajouter une nouvelle source (ex. LinkedIn) :
    1. Créer pipeline/scrapers/linkedin.py avec une classe héritant de BaseScraper
    2. L'importer et l'ajouter à la liste ci-dessous
    3. Rien d'autre à modifier
"""

from .base_scraper import BaseScraper

# Import des scrapers concrets au fur et à mesure qu'ils sont développés.
# Talent.io a été retiré : la plateforme a changé de modèle (recrutement
# inversé, plus de liste d'offres publique consultable/scrapable).
from .france_travail import FranceTravailScraper
from .wttj import WelcomeToTheJungleScraper
from .hellowork import HelloWorkScraper

SCRAPERS: list[type[BaseScraper]] = [
    FranceTravailScraper,
    WelcomeToTheJungleScraper,
    HelloWorkScraper,
]


def run_all(**config) -> list[dict]:
    """Exécute tous les scrapers enregistrés et retourne les offres collectées."""
    all_offers = []
    for scraper_cls in SCRAPERS:
        scraper = scraper_cls(**config)
        offers = scraper.run()
        all_offers.extend(o.to_dict() for o in offers)
    return all_offers
