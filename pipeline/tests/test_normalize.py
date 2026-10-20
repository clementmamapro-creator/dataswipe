"""
Tests unitaires pour normalize.py
"""
from pipeline.etl.normalize import (
    clean_offer,
    compute_dedup_key,
    deduplicate_offers,
    normalize_offers,
)


def test_dedup_key_matches_across_different_location_formats():
    """France Travail: 'Paris (75)', WTTJ: 'Paris', HelloWork: 'Paris - 75'
    doivent produire la même clé pour permettre la dédup inter-sources."""
    offer_ft = {"title": "Data Engineer H/F", "company": "Acme", "location": "Paris (75)"}
    offer_wttj = {"title": "Data Engineer", "company": "Acme", "location": "Paris"}
    offer_hw = {"title": "Data Engineer H/F", "company": "Acme", "location": "Paris - 75"}

    assert compute_dedup_key(offer_ft) == compute_dedup_key(offer_wttj) == compute_dedup_key(offer_hw)


def test_clean_offer_strips_whitespace_and_empties():
    offer = {
        "title": "  Data Engineer  ",
        "company": "",
        "location": "  Paris  ",
        "skills": ["Python", "Python", "", "SQL"],
        "salary_min": "45000",
        "salary_max": None,
    }
    cleaned = clean_offer(offer)

    assert cleaned["title"] == "Data Engineer"
    assert cleaned["company"] is None
    assert cleaned["location"] == "Paris"
    assert cleaned["skills"] == ["Python", "SQL"]
    assert cleaned["salary_min"] == 45000
    assert cleaned["salary_max"] is None


def test_dedup_key_ignores_case_accents_and_hf_suffix():
    offer_a = {"title": "Data Engineer H/F", "company": "Acme", "location": "Paris"}
    offer_b = {"title": "data engineer (H/F)", "company": "ACME", "location": "paris"}

    assert compute_dedup_key(offer_a) == compute_dedup_key(offer_b)


def test_deduplicate_offers_merges_cross_source_duplicates():
    offers = [
        {
            "source": "wttj", "source_id": "1", "title": "Data Engineer H/F",
            "company": "Acme", "location": "Paris", "description": "Courte description",
        },
        {
            "source": "hellowork", "source_id": "2", "title": "Data Engineer (H/F)",
            "company": "Acme", "location": "Paris", "description": "Une description beaucoup plus longue et détaillée",
        },
        {
            "source": "france_travail", "source_id": "3", "title": "Data Analyst",
            "company": "Autre Entreprise", "location": "Lyon", "description": "",
        },
    ]

    final_offers, stats = deduplicate_offers(offers)

    assert stats["input_count"] == 3
    assert stats["output_count"] == 2
    assert stats["duplicates_removed"] == 1

    merged = next(o for o in final_offers if o["company"] == "Acme")
    assert sorted(merged["merged_sources"]) == ["hellowork", "wttj"]
    # Garde la description la plus longue (celle de hellowork)
    assert "détaillée" in merged["description"]

    distinct = next(o for o in final_offers if o["company"] == "Autre Entreprise")
    assert distinct["merged_sources"] == ["france_travail"]


def test_normalize_offers_end_to_end():
    offers = [
        {"source": "wttj", "source_id": "1", "title": "  Data Scientist  ", "company": "X", "location": "Nantes", "skills": []},
    ]
    final_offers, stats = normalize_offers(offers)
    assert final_offers[0]["title"] == "Data Scientist"
    assert stats["output_count"] == 1
