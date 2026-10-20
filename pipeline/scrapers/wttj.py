"""
wttj.py

Scraper Welcome to the Jungle. Contrairement à France Travail, WTTJ n'a pas
d'API publique documentée — mais leur site s'appuie sur Algolia pour la
recherche, avec une clé "search-only" exposée côté client (utilisée par leur
propre barre de recherche). On interroge donc directement cet index Algolia,
plutôt que de parser le HTML de la page (plus fragile, casse à chaque refonte
visuelle du site).

⚠️ Ces valeurs (application ID, clé publique, nom d'index) sont celles
utilisées par le site au moment de l'écriture. Si le scraper cesse de
fonctionner du jour au lendemain, c'est probablement qu'elles ont changé
côté WTTJ — il suffit de les mettre à jour ici (pas de vraie "casse" de
sécurité, ce sont des valeurs publiques par design).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from .base_scraper import BaseScraper, JobOffer

logger = logging.getLogger("dataswipe.scraper.wttj")

ALGOLIA_APP_ID = "CSEKHVMS53"
ALGOLIA_SEARCH_KEY = "4bd8f6215d0cc52b26430765769e65a0"  # clé publique search-only
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID.lower()}-dsn.algolia.net/1/indexes/*/queries"
JOBS_INDEX = "wk_cms_jobs_production"

DEFAULT_KEYWORDS = [
    "data engineer",
    "data analyst",
    "data scientist",
    "chef de projet IT",
    "chef de projet data",
]
DEFAULT_HITS_PER_PAGE = 30


class WelcomeToTheJungleScraper(BaseScraper):
    source_name = "wttj"

    def __init__(self, **config: Any) -> None:
        super().__init__(**config)
        self.keywords = config.get("keywords", DEFAULT_KEYWORDS)
        if isinstance(self.keywords, str):
            self.keywords = [self.keywords]

    # ------------------------------------------------------------------ #
    # fetch — requêtes Algolia paginées, une par mot-clé
    # ------------------------------------------------------------------ #

    def fetch(self) -> list[dict[str, Any]]:
        headers = {
            "x-algolia-application-id": ALGOLIA_APP_ID,
            "x-algolia-api-key": ALGOLIA_SEARCH_KEY,
            "Content-Type": "application/x-www-form-urlencoded",  # particularité Algolia
            "Origin": "https://www.welcometothejungle.com",
            "Referer": "https://www.welcometothejungle.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        seen_ids: set[str] = set()
        all_results: list[dict[str, Any]] = []

        for keyword in self.keywords:
            logger.info("[wttj] Recherche pour le mot-clé : %s", keyword)
            page = 0

            while True:
                params = f"hitsPerPage={DEFAULT_HITS_PER_PAGE}&page={page}&query={keyword}"
                body = {"requests": [{"indexName": JOBS_INDEX, "params": params}]}

                response = requests.post(ALGOLIA_URL, headers=headers, json=body, timeout=30)

                if not response.ok:
                    logger.error("[wttj] Échec requête (HTTP %s) : %s", response.status_code, response.text[:500])
                    response.raise_for_status()

                data = response.json()
                results = data.get("results", [{}])[0]
                hits = results.get("hits", [])
                nb_pages = results.get("nbPages", 1)

                if not hits:
                    logger.info("[wttj] Aucun résultat (page %d). Clés reçues: %s", page, list(results.keys()))
                    break

                nouvelles = [h for h in hits if h.get("objectID") not in seen_ids]
                for h in nouvelles:
                    seen_ids.add(h.get("objectID"))
                all_results.extend(nouvelles)

                logger.info(
                    "[wttj] Page %d/%d récupérée : %d résultats (%d nouveaux, total: %d)",
                    page + 1, nb_pages, len(hits), len(nouvelles), len(all_results)
                )

                page += 1
                if page >= nb_pages:
                    break
                if page > 50:  # garde-fou
                    logger.warning("[wttj] Limite de pagination de sécurité atteinte (50 pages)")
                    break

        return all_results

    # ------------------------------------------------------------------ #
    # parse — Algolia renvoie déjà du JSON structuré
    # ------------------------------------------------------------------ #

    def parse(self, raw_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return raw_data

    # ------------------------------------------------------------------ #
    # to_normalized_schema — mapping vers JobOffer, calibré sur une vraie
    # réponse Algolia (voir historique : clés confirmées en conditions réelles)
    # ------------------------------------------------------------------ #

    def to_normalized_schema(self, parsed_items: list[dict[str, Any]]) -> list[JobOffer]:
        offers: list[JobOffer] = []

        for item in parsed_items:
            organization = item.get("organization", {}) or {}
            office = item.get("office", {}) or {}
            contract_names = item.get("contract_type_names", {}) or {}
            sectors = item.get("sectors", []) or []

            offers.append(JobOffer(
                source=self.source_name,
                source_id=str(item.get("objectID", "")),
                title=item.get("name", ""),
                company=organization.get("name"),
                location=office.get("city"),
                contract_type=contract_names.get("fr") or item.get("contract_type"),
                salary_min=item.get("salary_yearly_minimum") or item.get("salary_minimum"),
                salary_max=item.get("salary_maximum"),
                remote=item.get("remote"),
                # WTTJ n'expose pas de "compétences" à proprement parler comme France
                # Travail — on utilise les secteurs (ex: "Big Data", "IT / Digital")
                # comme proxy indicatif, utile pour un premier filtrage.
                skills=[
                    s.get("name", {}).get("fr") for s in sectors
                    if s.get("name", {}).get("fr")
                ],
                # Pas de champ "description" dédié dans l'index WTTJ — "profile" est
                # le seul bloc de texte substantiel (description du poste ET du
                # profil recherché, souvent mélangés, rédigés par l'entreprise).
                description=item.get("profile"),
                url=self._build_url(item),
                published_at=item.get("published_at"),
            ))

        return offers

    @staticmethod
    def _build_url(item: dict[str, Any]) -> Optional[str]:
        slug = item.get("slug")
        org_slug = (item.get("organization") or {}).get("slug")
        if slug and org_slug:
            return f"https://www.welcometothejungle.com/fr/companies/{org_slug}/jobs/{slug}"
        return None


if __name__ == "__main__":
    # Test manuel : python -m pipeline.scrapers.wttj
    # Affiche en priorité les clés brutes du 1er résultat pour calibrer le mapping.
    logging.basicConfig(level=logging.INFO)

    scraper = WelcomeToTheJungleScraper(keywords=["data engineer"])
    raw = scraper.fetch()
    print(f"\n{len(raw)} résultats bruts récupérés")
    if raw:
        print("\n--- Clés disponibles sur le 1er résultat brut ---")
        print(list(raw[0].keys()))
        print("\n--- Contenu complet du 1er résultat brut ---")
        print(raw[0])

    offers = scraper.to_normalized_schema(raw)
    if offers:
        print("\n--- Après mapping vers JobOffer ---")
        print(offers[0].to_dict())
