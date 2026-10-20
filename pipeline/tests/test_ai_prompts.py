"""
Tests unitaires pour les modules ai/ — se limitent à la construction des
prompts (build_prompt), sans appeler la vraie API Anthropic. L'appel réel
est vérifié manuellement avec une clé API valide.
"""
from pipeline.ai import coaching, cover_letter, cv_adapter


SAMPLE_OFFER = {
    "title": "Data Engineer H/F",
    "company": "Acme",
    "description": "Nous recherchons un Data Engineer maîtrisant Python et Airflow.",
}


def test_cv_adapter_prompt_includes_cv_and_offer():
    prompt = cv_adapter.build_prompt("Mon CV : 5 ans d'expérience Python", SAMPLE_OFFER)
    assert "5 ans d'expérience Python" in prompt
    assert "Data Engineer H/F" in prompt
    assert "Acme" in prompt


def test_cover_letter_prompt_includes_cv_and_offer():
    prompt = cover_letter.build_prompt("Mon CV : 5 ans d'expérience Python", SAMPLE_OFFER)
    assert "5 ans d'expérience Python" in prompt
    assert "Data Engineer H/F" in prompt


def test_coaching_prompt_lists_missing_skills():
    prompt = coaching.build_prompt(SAMPLE_OFFER, ["Airflow", "Docker"])
    assert "Airflow, Docker" in prompt
    assert "Data Engineer H/F" in prompt


def test_coaching_returns_early_message_when_no_missing_skills():
    result = coaching.generate_coaching(SAMPLE_OFFER, [])
    assert "aucune compétence manquante" in result.lower()
