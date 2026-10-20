"""
Tests unitaires pour load.py — se limite à la construction/l'échappement SQL,
sans connexion réelle. L'insertion réelle est vérifiée manuellement via
`python -m pipeline.etl.load` (nécessite Docker + docker-compose).
"""
from pipeline.etl.load import _sql_array, _sql_int, _sql_str, _offer_to_values_row


def test_sql_str_escapes_quotes():
    assert _sql_str("Data Engineer") == "'Data Engineer'"
    assert _sql_str("L'équipe") == "'L''équipe'"
    assert _sql_str(None) == "NULL"


def test_sql_int_handles_none_and_invalid():
    assert _sql_int(45000) == "45000"
    assert _sql_int(None) == "NULL"
    assert _sql_int("abc") == "NULL"


def test_sql_array_builds_postgres_array_literal():
    assert _sql_array(["Python", "SQL"]) == "ARRAY['Python','SQL']::text[]"
    assert _sql_array([]) == "ARRAY[]::text[]"
    assert _sql_array(None) == "ARRAY[]::text[]"


def test_offer_to_values_row_produces_valid_tuple_syntax():
    offer = {
        "dedup_key": "key1", "source": "wttj", "source_id": "1",
        "merged_sources": ["wttj"], "title": "Data Engineer", "company": "Acme",
        "location": "Paris", "contract_type": "CDI", "salary_min": 45000,
        "salary_max": None, "remote": "partial", "skills": ["Python"],
        "description": "Description", "url": "https://example.com",
        "published_at": "2026-01-01", "collected_at": "2026-01-01T00:00:00",
    }
    row = _offer_to_values_row(offer)
    assert row.startswith("(") and row.endswith(")")
    assert "'Data Engineer'" in row
    assert "45000" in row