"""
hellowork.py

Scraper HelloWork. Contrairement à WTTJ, aucune API publique de type Algolia
n'a été identifiée côté client — HelloWork rend ses pages de résultats
entièrement côté serveur (le contenu est visible sans JavaScript, ce qui le
rend indexable par Google). On scrape donc le HTML directement.

⚠️ La récupération de la description (fetch_description) est du "best-effort
calibré" : les sélecteurs exacts de la page détail n'ont pas pu être vérifiés
en conditions réelles avant ce commit — on extrait tout le texte visible de
la page, nettoyé des balises de navigation/scripts, plutôt que de cibler un
bloc précis. Voir le bloc __main__ (mode debug_limit) pour calibrer sur un
vrai résultat avant de lancer sur la totalité des offres.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

from .base_scraper import BaseScraper, JobOffer

logger = logging.getLogger("dataswipe.scraper.hellowork")

BASE_URL = "https://www.hellowork.com"
SEARCH_URL = f"{BASE_URL}/fr-fr/emploi/recherche.html"
JOB_LINK_PATTERN = re.compile(r"^/fr-fr/emplois/(\d+)\.html")

DEFAULT_KEYWORDS = [
    "data engineer",
    "data analyst",
    "data scientist",
    "chef de projet IT",
    "chef de projet data",
]

CONTRACT_TYPES = [
    "CDI", "CDD", "Intérim", "Stage", "Alternance", "Indépendant",
    "Franchise", "Associé", "Fonctionnaire", "Freelance", "Stage de lycée",
]
SALARY_PATTERN = re.compile(r"([\d\s]+(?:-[\d\s]+)?)\s*€\s*/\s*(an|mois|jour|heure)", re.IGNORECASE)
REMOTE_PATTERN = re.compile(r"Télétravail (complet|partiel|occasionnel)|Pas de télétravail", re.IGNORECASE)
MAX_PAGES = 60  # garde-fou
DESCRIPTION_MAX_WORKERS = 8   # requêtes en parallèle pour les pages détail
DESCRIPTION_MAX_CHARS = 6000  # tronque les descriptions trop longues


def _slugify(text: str) -> str:
    """Convertit un mot-clé en slug d'URL HelloWork (ex: 'data engineer' -> 'data-engineer')."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


class HelloWorkScraper(BaseScraper):
    source_name = "hellowork"

    def __init__(self, **config: Any) -> None:
        super().__init__(**config)
        self.keywords = config.get("keywords", DEFAULT_KEYWORDS)
        if isinstance(self.keywords, str):
            self.keywords = [self.keywords]
        # fetch_descriptions=False permet de désactiver l'étape (tests rapides,
        # ou si HelloWork bloque/ralentit trop de requêtes détail)
        self.fetch_descriptions = config.get("fetch_descriptions", True)
        # debug_limit : ne récupère la description que pour les N premières
        # offres (calibrage rapide sans attendre des milliers de requêtes)
        self.debug_limit = config.get("debug_limit")

    # ------------------------------------------------------------------ #
    # fetch — scraping HTML paginé, un mot-clé à la fois, puis récupération
    # des descriptions en parallèle
    # ------------------------------------------------------------------ #

    def fetch(self) -> list[dict[str, Any]]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "fr-FR,fr;q=0.9",
        }

        seen_ids: set[str] = set()
        all_results: list[dict[str, Any]] = []

        for keyword in self.keywords:
            logger.info("[hellowork] Recherche pour le mot-clé : %s", keyword)
            page = 1

            while page <= MAX_PAGES:
                params = {"k": keyword, "d": "all"}
                if page > 1:
                    params["p"] = page

                response = requests.get(SEARCH_URL, headers=headers, params=params, timeout=30)

                if not response.ok:
                    logger.error("[hellowork] Échec requête (HTTP %s) sur %s", response.status_code, response.url)
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                job_links = [
                    a for a in soup.find_all("a", href=JOB_LINK_PATTERN)
                    if a.get_text(strip=True)  # écarte les liens sans texte (ex: liens image)
                ]

                if not job_links:
                    logger.info("[hellowork] Aucune offre trouvée page %d — fin de pagination", page)
                    break

                nouvelles = 0
                for link in job_links:
                    match = JOB_LINK_PATTERN.match(link["href"])
                    job_id = match.group(1)
                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)
                    nouvelles += 1

                    card_text = self._extract_card_text(link)
                    all_results.append({
                        "id": job_id,
                        "url": BASE_URL + link["href"],
                        "card_text": card_text,
                    })

                logger.info(
                    "[hellowork] Page %d récupérée : %d offres (%d nouvelles, total: %d)",
                    page, len(job_links), nouvelles, len(all_results)
                )

                if nouvelles == 0:
                    # Toute la page était déjà vue : on a probablement dépassé la fin réelle
                    break

                page += 1

        if self.fetch_descriptions:
            self._fetch_all_descriptions(all_results, headers)

        return all_results

    def _fetch_all_descriptions(self, items: list[dict[str, Any]], headers: dict) -> None:
        """Récupère la description de chaque offre en parallèle (I/O-bound,
        donc des threads suffisent, pas besoin de multiprocessing)."""
        targets = items[: self.debug_limit] if self.debug_limit else items
        logger.info("[hellowork] Récupération des descriptions pour %d offres (%d workers)...", len(targets), DESCRIPTION_MAX_WORKERS)

        done = 0
        with ThreadPoolExecutor(max_workers=DESCRIPTION_MAX_WORKERS) as executor:
            future_to_item = {
                executor.submit(self._fetch_description, item["url"], headers): item
                for item in targets
            }
            for future in as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    item["description"] = future.result()
                except Exception:
                    logger.exception("[hellowork] Échec récupération description : %s", item.get("url"))
                    item["description"] = None
                done += 1
                if done % 200 == 0:
                    logger.info("[hellowork] Descriptions récupérées : %d/%d", done, len(targets))

        logger.info("[hellowork] Descriptions récupérées : %d/%d (terminé)", done, len(targets))

    @staticmethod
    def _fetch_description(url: str, headers: dict) -> Optional[str]:
        """Récupère et nettoie le texte de la page détail d'une offre.
        Best-effort : retire scripts/styles/nav/footer/header, garde le
        reste du texte visible (pas de sélecteur CSS précis calibré)."""
        try:
            response = requests.get(url, headers=headers, timeout=20)
            if not response.ok:
                return None

            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                tag.decompose()

            text = soup.get_text(separator="\n", strip=True)
            # Réduit les lignes vides multiples laissées par le nettoyage
            text = re.sub(r"\n{2,}", "\n", text)
            return text[:DESCRIPTION_MAX_CHARS] if text else None
        except requests.RequestException:
            return None

    @staticmethod
    def _extract_card_text(link) -> str:
        """
        Remonte jusqu'à un ancêtre plausible représentant la carte d'offre
        complète (article, li, ou div englobant), pour en extraire le texte
        brut — utilisé ensuite par des heuristiques regex plutôt que des
        sélecteurs CSS précis (non calibrés).
        """
        container = link
        for _ in range(6):  # remonte jusqu'à 6 niveaux au maximum
            if container.parent is None:
                break
            container = container.parent
            if container.name in ("article", "li"):
                break
        return container.get_text(separator=" | ", strip=True)

    # ------------------------------------------------------------------ #
    # parse — pas de transformation supplémentaire nécessaire ici
    # ------------------------------------------------------------------ #

    def parse(self, raw_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return raw_data

    # ------------------------------------------------------------------ #
    # to_normalized_schema — extraction heuristique depuis le texte de carte
    # ------------------------------------------------------------------ #

    def to_normalized_schema(self, parsed_items: list[dict[str, Any]]) -> list[JobOffer]:
        offers: list[JobOffer] = []
        noise_prefixes = (
            "voir l'offre", "voir l’offre", "il y a", "super recruteur",
            "suivi de candidature", "cette entreprise souhaite rester anonyme",
        )

        for item in parsed_items:
            text = item.get("card_text", "")
            parts = [p.strip() for p in text.split("|") if p.strip()]
            parts = [p for p in parts if not p.lower().startswith(noise_prefixes)]

            title = parts[0] if parts else ""

            contract_type = next((p for p in parts if p in CONTRACT_TYPES), None)

            salary_min = None
            salary_match = SALARY_PATTERN.search(text)
            if salary_match:
                # group(1) est ex: "40 000 - 50 000 " (avec espace insécable fine
                # \u202f) — on ne garde que le premier nombre (avant un éventuel "-")
                first_number_raw = salary_match.group(1).split("-")[0]
                digits = re.sub(r"\D", "", first_number_raw)
                if digits:
                    salary_min = int(digits)

            remote = None
            remote_match = REMOTE_PATTERN.search(text)
            if remote_match:
                remote = remote_match.group(0)

            def is_structural(p: str) -> bool:
                return (
                    p in CONTRACT_TYPES
                    or SALARY_PATTERN.search(p) is not None
                    or REMOTE_PATTERN.search(p) is not None
                )

            company = None
            location = None
            remaining = parts[1:]
            if remaining and not is_structural(remaining[0]):
                if re.match(r"^[\wÀ-ÿ\s\-'\.]+ - \d{2,3}$", remaining[0]) or len(remaining) == 1:
                    location = remaining[0]
                else:
                    company = remaining[0]
                    if len(remaining) > 1 and not is_structural(remaining[1]):
                        location = remaining[1]

            offers.append(JobOffer(
                source=self.source_name,
                source_id=item.get("id", ""),
                title=title,
                company=company,
                location=location,
                contract_type=contract_type,
                salary_min=salary_min,
                salary_max=None,
                remote=remote,
                skills=[],
                description=item.get("description"),
                url=item.get("url"),
                published_at=None,
            ))

        return offers


if __name__ == "__main__":
    # Test manuel calibré : ne récupère la description que pour les 5
    # premières offres (debug_limit=5), pour vérifier le résultat avant de
    # lancer sur la totalité (plusieurs milliers de requêtes sinon).
    logging.basicConfig(level=logging.INFO)

    scraper = HelloWorkScraper(keywords=["data engineer"], debug_limit=5)
    raw = scraper.fetch()
    print(f"\n{len(raw)} résultats bruts récupérés")
    if raw:
        print("\n--- 1er résultat brut (id, url, card_text, description) ---")
        first = raw[0]
        print(f"id: {first.get('id')}")
        print(f"url: {first.get('url')}")
        print(f"card_text: {first.get('card_text')}")
        print(f"\ndescription ({len(first.get('description') or '')} caractères) :")
        print(first.get("description"))

    offers = scraper.to_normalized_schema(raw)
    if offers:
        print("\n--- Après mapping vers JobOffer (1er élément) ---")
        print(offers[0].to_dict())

