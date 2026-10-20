"""
Tests unitaires pour cv_parser.py — se limite à la validation des formats,
sans fichier réel (le parsing PDF/DOCX réel est vérifié manuellement).
"""
import pytest

from pipeline.matching.cv_parser import parse_cv


def test_unsupported_format_raises():
    with pytest.raises(ValueError, match="non supporté"):
        parse_cv("cv.txt")


def test_old_doc_format_raises_helpful_message():
    with pytest.raises(ValueError, match=r"\.doc"):
        parse_cv("cv.doc")
