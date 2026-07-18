from datetime import datetime

from alpha_os.core.enums import InstitutionalClassification
from alpha_os.core.models import InstitutionalAssessment
from alpha_os.engine.signal_engine import _institutional_factor, _institutional_veto


def _assessment(score: float, classification: InstitutionalClassification) -> InstitutionalAssessment:
    return InstitutionalAssessment(
        ticker="TEST",
        score=score,
        classification=classification,
        confidence=0.6,
        signals=[],
        data_freshness="recent",
        rationale="test",
        generated_at=datetime.utcnow(),
    )


def test_strong_distribution_vetoes_long_hypothesis():
    """Sección 6: distribución institucional fuerte debe bloquear una
    hipótesis alcista, no solo restarle puntos."""
    assessment = _assessment(-80, InstitutionalClassification.STRONG_DISTRIBUTION)
    assert _institutional_veto(assessment, "long") is True


def test_strong_distribution_does_not_veto_short_hypothesis():
    """La misma distribución fuerte en realidad CONFIRMA una tesis corta,
    no debe bloquearla."""
    assessment = _assessment(-80, InstitutionalClassification.STRONG_DISTRIBUTION)
    assert _institutional_veto(assessment, "short") is False


def test_strong_accumulation_vetoes_short_hypothesis():
    assessment = _assessment(80, InstitutionalClassification.STRONG_ACCUMULATION)
    assert _institutional_veto(assessment, "short") is True


def test_moderate_distribution_does_not_veto():
    """Sección 6: solo distribución/acumulación FUERTE bloquea — moderada
    debe seguir siendo solo un factor más (resta convicción, no bloquea)."""
    assessment = _assessment(-40, InstitutionalClassification.MODERATE_DISTRIBUTION)
    assert _institutional_veto(assessment, "long") is False
    factors = _institutional_factor(assessment, "long")
    assert len(factors) == 1
    assert factors[0].weight_pct < 0


def test_neutral_classification_produces_no_factor():
    assessment = _assessment(0, InstitutionalClassification.NEUTRAL)
    assert _institutional_factor(assessment, "long") == []


def test_insufficient_data_produces_no_factor():
    assessment = _assessment(0, InstitutionalClassification.INSUFFICIENT_DATA)
    assert _institutional_factor(assessment, "long") == []
