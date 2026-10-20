"""
run_all_test.py

Lance les 3 scrapers actifs (France Travail, WTTJ, HelloWork) via le registre,
avec les mots-clés par défaut de chacun, et affiche un résumé du volume
collecté par source.

Usage : python -m pipeline.run_all_test
"""

import logging
import time
from collections import Counter

from dotenv import load_dotenv

from pipeline.scrapers.registry import SCRAPERS

logging.basicConfig(level=logging.INFO)
load_dotenv()

if __name__ == "__main__":
    all_offers = []
    per_source_counts = Counter()
    start = time.time()

    for scraper_cls in SCRAPERS:
        print(f"\n{'=' * 60}")
        print(f"Lancement : {scraper_cls.__name__}")
        print(f"{'=' * 60}")

        scraper = scraper_cls()
        t0 = time.time()
        offers = scraper.run()
        elapsed = time.time() - t0

        per_source_counts[scraper.source_name] = len(offers)
        all_offers.extend(offers)

        print(f"-> {len(offers)} offres collectées en {elapsed:.1f}s")

    total_elapsed = time.time() - start

    print(f"\n{'=' * 60}")
    print("RÉSUMÉ")
    print(f"{'=' * 60}")
    for source, count in per_source_counts.items():
        print(f"  {source:20s} : {count:5d} offres")
    print(f"  {'TOTAL':20s} : {len(all_offers):5d} offres")
    print(f"\nTemps total : {total_elapsed:.1f}s ({total_elapsed / 60:.1f} min)")

    # Aperçu rapide des doublons potentiels inter-sources (par titre exact,
    # heuristique grossière — le vrai travail de dédup se fera dans normalize.py)
    titles = [o.title.strip().lower() for o in all_offers if o.title]
    title_counts = Counter(titles)
    duplicates = {t: c for t, c in title_counts.items() if c > 1}
    if duplicates:
        print(f"\n{len(duplicates)} titres identiques apparaissant sur plusieurs offres")
        print("(à affiner dans normalize.py — un même titre peut aussi juste être un intitulé de poste courant)")
