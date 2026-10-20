"""
france_travail.py

Scraper de la source officielle France Travail (ex Pôle Emploi), via l'API
"Offres d'emploi v2" en accès libre (authentification OAuth2 client_credentials).

Identifiants requis dans .env :
    FRANCE_TRAVAIL_CLIENT_ID=...
    FRANCE_TRAVAIL_CLIENT_SECRET=...

Doc API : https://francetravail.io/data/api/offres-emploi
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any, Optional

import requests

from .base_scraper import BaseScraper, JobOffer

logger = logging.getLogger("dataswipe.scraper.france_travail")

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"

# Mots-clés par défaut pour cibler le secteur data — une recherche distincte par terme,
# car l'API ne traite pas "data engineer,data analyst" comme un OU logique correct.
DEFAULT_KEYWORDS = [
    "data engineer",
    "data analyst",
    "data scientist",
    "chef de projet IT",
    "chef de projet data",
]
DEFAULT_RANGE_SIZE = 150  # max autorisé par l'API par page (0-149 = 150 résultats)


class FranceTravailScraper(BaseScraper):
    source_name = "france_travail"

    def __init__(self, **config: Any) -> None:
        super().__init__(**config)
        self.client_id = (config.get("client_id") or os.getenv("FRANCE_TRAVAIL_CLIENT_ID") or "").strip()
        self.client_secret = (config.get("client_secret") or os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET") or "").strip()
        self.keywords = config.get("keywords", DEFAULT_KEYWORDS)
        if isinstance(self.keywords, str):
            self.keywords = [self.keywords]
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "FRANCE_TRAVAIL_CLIENT_ID / FRANCE_TRAVAIL_CLIENT_SECRET manquants. "
                "Renseignez-les dans votre fichier .env."
            )

        logger.info(
            "[france_travail] Identifiants chargés — client_id: %d caractères (%s...%s), "
            "client_secret: %d caractères (%s...%s)",
            len(self.client_id), self.client_id[:6], self.client_id[-4:],
            len(self.client_secret), self.client_secret[:4], self.client_secret[-4:],
        )

    # ------------------------------------------------------------------ #
    # Authentification OAuth2 (client_credentials)
    # ------------------------------------------------------------------ #

    def _get_access_token(self) -> str:
        """Récupère un token valide, en le mettant en cache jusqu'à expiration."""
        if self._token and time.time() < self._token_expires_at:
            return self._token

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            # Le scope inclut application_{client_id}, requis par France Travail
            "scope": f"api_offresdemploiv2 o2dsoffre application_{self.client_id}",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        # On encode nous-mêmes le corps de la requête (au lieu de laisser requests
        # le faire via data=payload) pour garantir un encodage identique à celui
        # qui fonctionne en curl — évite tout écart d'encodage sur le paramètre scope.
        from urllib.parse import urlencode
        body = urlencode(payload)

        response = requests.post(TOKEN_URL, data=body, headers=headers, timeout=30)
        if not response.ok:
            logger.error(
                "[france_travail] Échec authentification OAuth2 (HTTP %s) : %s",
                response.status_code, response.text
            )
        response.raise_for_status()
        data = response.json()

        self._token = data["access_token"]
        # expires_in est en secondes ; on retire une marge de sécurité de 30s
        self._token_expires_at = time.time() + data.get("expires_in", 1200) - 30
        logger.info("[france_travail] Token OAuth2 obtenu (expire dans %ss)", data.get("expires_in"))
        return self._token

    # ------------------------------------------------------------------ #
    # fetch — appel API avec pagination
    # ------------------------------------------------------------------ #

    def fetch(self) -> list[dict[str, Any]]:
        token = self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        seen_ids: set[str] = set()
        all_results: list[dict[str, Any]] = []

        for keyword in self.keywords:
            logger.info("[france_travail] Recherche pour le mot-clé : %s", keyword)
            start = 0
            page_size = DEFAULT_RANGE_SIZE

            while True:
                params = {
                    "motsCles": keyword,
                    "range": f"{start}-{start + page_size - 1}",
                }
                response = requests.get(SEARCH_URL, headers=headers, params=params, timeout=30)

                logger.info(
                    "[france_travail] Requête recherche — status %s, Content-Range: %s",
                    response.status_code, response.headers.get("Content-Range")
                )

                # 204 = aucun résultat sur cette page -> fin de pagination
                if response.status_code == 204:
                    logger.info("[france_travail] 204 No Content reçu — aucune offre pour ces critères")
                    break
                # 206 = résultat partiel (pagination), 200 = résultat complet
                if response.status_code not in (200, 206):
                    logger.error("[france_travail] Réponse inattendue : %s", response.text[:500])
                    response.raise_for_status()

                data = response.json()
                offres = data.get("resultats", [])
                if not offres:
                    logger.info("[france_travail] Aucune offre dans data['resultats']. Clés reçues: %s", list(data.keys()))
                    break

                # Déduplication : une même offre peut ressortir sur plusieurs mots-clés
                nouvelles = [o for o in offres if o.get("id") not in seen_ids]
                for o in nouvelles:
                    seen_ids.add(o.get("id"))
                all_results.extend(nouvelles)

                logger.info(
                    "[france_travail] Page récupérée : %d offres (%d nouvelles, total: %d)",
                    len(offres), len(nouvelles), len(all_results)
                )

                if len(offres) < page_size:
                    break  # dernière page atteinte pour ce mot-clé
                start += page_size

                # Garde-fou pour ne pas tourner indéfiniment en cas de comportement inattendu
                if start > 3000:
                    logger.warning("[france_travail] Limite de pagination de sécurité atteinte (3000)")
                    break

        return all_results

    # ------------------------------------------------------------------ #
    # parse — l'API renvoie déjà du JSON structuré, peu de travail ici
    # ------------------------------------------------------------------ #

    def parse(self, raw_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return raw_data

    # ------------------------------------------------------------------ #
    # to_normalized_schema — mapping vers JobOffer
    # ------------------------------------------------------------------ #

    def to_normalized_schema(self, parsed_items: list[dict[str, Any]]) -> list[JobOffer]:
        offers: list[JobOffer] = []

        for item in parsed_items:
            salaire = item.get("salaire", {}) or {}
            lieu = item.get("lieuTravail", {}) or {}
            entreprise = item.get("entreprise", {}) or {}
            competences = item.get("competences", []) or []

            offers.append(JobOffer(
                source=self.source_name,
                source_id=item.get("id", ""),
                title=item.get("intitule", ""),
                company=entreprise.get("nom"),
                location=lieu.get("libelle"),
                contract_type=item.get("typeContrat"),
                salary_min=self._parse_salary(salaire.get("libelle")),
                salary_max=None,  # France Travail donne souvent un libellé texte, pas un min/max structuré
                remote=self._parse_remote(item),
                skills=[c.get("libelle") for c in competences if c.get("libelle")],
                description=item.get("description"),
                url=item.get("origineOffre", {}).get("urlOrigine"),
                published_at=item.get("dateCreation"),
            ))

        return offers

    @staticmethod
    def _parse_salary(libelle: Optional[str]) -> Optional[int]:
        """Best-effort : France Travail renvoie un libellé texte libre pour le salaire.
        On ne fait pas de parsing agressif ici — à affiner au Sprint 2 (ETL/normalize)."""
        return None

    @staticmethod
    def _parse_remote(item: dict[str, Any]) -> Optional[str]:
        # Certaines offres portent un champ "teletravail" — à confirmer/affiner selon les retours API réels
        teletravail = item.get("teletravail")
        if teletravail:
            return "hybrid"
        return None


if __name__ == "__main__":
    # Test manuel rapide : python -m pipeline.scrapers.france_travail
    logging.basicConfig(level=logging.INFO)
    from dotenv import load_dotenv
    load_dotenv()

    scraper = FranceTravailScraper()
    offers = scraper.run()
    print(f"{len(offers)} offres collectées")
    if offers:
        print(offers[0].to_dict())
