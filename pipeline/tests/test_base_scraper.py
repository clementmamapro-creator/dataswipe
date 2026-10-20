"""
Tests unitaires pour base_scraper.py
"""
import pytest
from pipeline.scrapers.base_scraper import BaseScraper, JobOffer


def test_joboffer_to_dict():
    offer = JobOffer(source="test", source_id="1", title="Data Engineer")
    d = offer.to_dict()
    assert d["title"] == "Data Engineer"
    assert d["source"] == "test"


def test_base_scraper_is_abstract():
    with pytest.raises(TypeError):
        BaseScraper()
