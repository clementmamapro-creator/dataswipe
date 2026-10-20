"""
Tests unitaires pour scoring.py
"""
from pipeline.matching.scoring import compute_match_score


def test_perfect_match():
    result = compute_match_score(["Python", "SQL", "Airflow"], ["Python", "SQL", "Airflow"])
    assert result.score == 100.0
    assert result.missing_skills == []


def test_partial_match():
    result = compute_match_score(["Python", "SQL"], ["Python", "SQL", "Airflow", "Docker"])
    assert result.score == 50.0
    assert set(result.matched_skills) == {"Python", "SQL"}
    assert set(result.missing_skills) == {"Airflow", "Docker"}


def test_no_match():
    result = compute_match_score(["Java", "C#"], ["Python", "SQL"])
    assert result.score == 0.0
    assert result.matched_skills == []


def test_candidate_has_more_skills_than_required():
    """Le candidat a plus de compétences que demandé -> score toujours 100%,
    pas pénalisé pour un surplus de compétences."""
    result = compute_match_score(["Python", "SQL", "Docker", "AWS", "Kubernetes"], ["Python", "SQL"])
    assert result.score == 100.0


def test_offer_with_no_skills_returns_zero_not_hundred():
    """Une offre sans compétence détectée ne doit pas donner un score
    artificiellement à 100% (division par zéro évitée) ni fausser le
    classement en donnant l'impression d'un match parfait."""
    result = compute_match_score(["Python", "SQL"], [])
    assert result.score == 0.0
