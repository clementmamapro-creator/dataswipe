"""
Tests unitaires pour extract_skills.py
"""
from pipeline.matching.extract_skills import extract_skills, get_offer_skills


def test_extract_skills_basic():
    text = "Je maîtrise Python, SQL et Power BI depuis 3 ans. J'utilise aussi Airflow au quotidien."
    skills = extract_skills(text)
    assert "Python" in skills
    assert "SQL" in skills
    assert "Power BI" in skills
    assert "Airflow" in skills


def test_extract_skills_avoids_false_positives():
    """'R' ne doit pas matcher dans 'Recherche', 'C#' ne doit pas planter la regex."""
    text = "Poste en Recherche et développement, environnement C#."
    skills = extract_skills(text)
    assert "R" not in skills
    assert "C#" in skills


def test_extract_skills_case_insensitive():
    text = "python SQL power bi"
    skills = extract_skills(text)
    assert "Python" in skills
    assert "SQL" in skills
    assert "Power BI" in skills


def test_extract_skills_handles_aliases():
    text = "Expérience avec PowerBI, ML, et Postgres."
    skills = extract_skills(text)
    assert "Power BI" in skills
    assert "Machine Learning" in skills
    assert "PostgreSQL" in skills


def test_extract_skills_empty_text():
    assert extract_skills(None) == []
    assert extract_skills("") == []
    assert extract_skills("Aucune compétence technique ici") == []


def test_get_offer_skills_uses_existing_when_present():
    offer = {"skills": ["Big Data"], "title": "Data Engineer Python", "description": "SQL requis"}
    skills = get_offer_skills(offer)
    assert "Big Data" in skills
    assert "Python" in skills
    assert "SQL" in skills


def test_get_offer_skills_falls_back_to_text_when_empty():
    offer = {"skills": [], "title": "Data Analyst", "description": "Maîtrise de SQL et Tableau exigée"}
    skills = get_offer_skills(offer)
    assert "SQL" in skills
    assert "Tableau" in skills
