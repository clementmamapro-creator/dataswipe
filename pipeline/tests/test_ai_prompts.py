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


def _capture(monkeypatch, module):
    """Remplace l'appel au modèle : renvoie un texte fixe et mémorise le prompt envoyé."""
    seen = {}

    def fake(system, prompt, **kwargs):
        seen["system"], seen["prompt"] = system, prompt
        return "## Corps du document\nTexte généré."

    monkeypatch.setattr(module._llm, "complete", fake)
    return seen


def test_cv_adapter_prompt_includes_cv_and_offer(monkeypatch):
    seen = _capture(monkeypatch, cv_adapter)
    cv_adapter.adapt_cv("Mon CV : 5 ans d'expérience Python", SAMPLE_OFFER)
    assert "5 ans d'expérience Python" in seen["prompt"]
    assert "Data Engineer" in seen["prompt"]
    assert "Acme" in seen["prompt"]


def test_cover_letter_prompt_includes_cv_and_offer(monkeypatch):
    seen = _capture(monkeypatch, cover_letter)
    cover_letter.generate_cover_letter("Mon CV : 5 ans d'expérience Python", SAMPLE_OFFER)
    assert "5 ans d'expérience Python" in seen["prompt"]
    assert "Data Engineer" in seen["prompt"]


def test_niveau_impose_par_le_profil_utilisateur(monkeypatch):
    seen = _capture(monkeypatch, cv_adapter)
    cv_adapter.adapt_cv("Mon CV : alternance data", SAMPLE_OFFER, user={"level": "junior"})
    assert "junior" in seen["prompt"].lower()


def test_coaching_prompt_lists_missing_skills():
    prompt = coaching.build_prompt(SAMPLE_OFFER, ["Airflow", "Docker"])
    assert "Airflow, Docker" in prompt
    assert "Data Engineer H/F" in prompt


def test_coaching_returns_early_message_when_no_missing_skills():
    result = coaching.generate_coaching(SAMPLE_OFFER, [])
    assert "aucune compétence manquante" in result.lower()
