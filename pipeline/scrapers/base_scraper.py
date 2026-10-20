"""
base_scraper.py

Interface commune à tous les scrapers de DataSwipe.

Chaque source (France Travail, WTTJ, Talent.io, HelloWork, LinkedIn plus tard...)
doit implémenter une classe qui hérite de BaseScraper et respecte ces 3 étapes :

    fetch()                -> récupère les données brutes depuis la source
    parse(raw_data)         -> transforme le brut en une liste de dicts exploitables
    to_normalized_schema()  -> convertit chaque offre vers le schéma unifié DataSwipe

Ajouter une nouvelle source = créer un fichier qui hérite de BaseScraper
et l'enregistrer dans registry.py. Rien d'autre à modifier (ni le DAG,
ni l'ETL, ni la base de données).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Optional
import logging

logger = logging.getLogger("dataswipe.scraper")


@dataclass
class JobOffer:
    """
    Schéma unifié DataSwipe. Toutes les sources doivent produire des offres
    sous cette forme avant insertion en base — c'est le contrat entre les
    scrapers et le reste du pipeline (ETL, matching, base de données).
    """
    source: str                       # ex: "france_travail", "wttj", "hellowork"
    source_id: str                    # identifiant unique côté source (pour dédup)
    title: str
    company: Optional[str] = None
    location: Optional[str] = None
    contract_type: Optional[str] = None   # CDI, CDD, Alternance, Stage...
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    remote: Optional[str] = None          # "full", "hybrid", "none", None si inconnu
    skills: list[str] = field(default_factory=list)
    description: Optional[str] = None
    url: Optional[str] = None
    published_at: Optional[str] = None    # ISO 8601, si connu
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseScraper(ABC):
    """
    Classe abstraite à hériter par chaque scraper de source.

    Usage type dans un scraper concret :

        class FranceTravailScraper(BaseScraper):
            source_name = "france_travail"

            def fetch(self) -> Any:
                ...  # appel API / requête HTTP

            def parse(self, raw_data: Any) -> list[dict]:
                ...  # extraction des champs bruts

            def to_normalized_schema(self, parsed_items: list[dict]) -> list[JobOffer]:
                ...  # mapping vers JobOffer
    """

    # À redéfinir dans chaque scraper concret, ex: "france_travail", "wttj"...
    source_name: str = "unknown"

    def __init__(self, **config: Any) -> None:
        self.config = config

    @abstractmethod
    def fetch(self) -> Any:
        """Récupère les données brutes depuis la source (API ou HTML)."""
        raise NotImplementedError

    @abstractmethod
    def parse(self, raw_data: Any) -> list[dict[str, Any]]:
        """Transforme les données brutes en liste de dictionnaires exploitables."""
        raise NotImplementedError

    @abstractmethod
    def to_normalized_schema(self, parsed_items: list[dict[str, Any]]) -> list[JobOffer]:
        """Convertit chaque item parsé vers le schéma unifié JobOffer."""
        raise NotImplementedError

    def run(self) -> list[JobOffer]:
        """
        Point d'entrée unique appelé par le DAG Airflow via le registre.
        Orchestre fetch -> parse -> to_normalized_schema, avec logs et
        gestion d'erreur commune à toutes les sources.
        """
        logger.info("[%s] Début de la collecte", self.source_name)
        try:
            raw_data = self.fetch()
            parsed_items = self.parse(raw_data)
            offers = self.to_normalized_schema(parsed_items)
            logger.info("[%s] %d offres collectées", self.source_name, len(offers))
            return offers
        except Exception:
            logger.exception("[%s] Échec de la collecte", self.source_name)
            # On ne bloque jamais les autres scrapers : une source en échec
            # ne doit pas empêcher les autres de tourner dans le DAG.
            return []
