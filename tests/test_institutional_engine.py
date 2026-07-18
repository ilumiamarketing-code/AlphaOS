from datetime import date, datetime, timedelta

from alpha_os.adapters.institutional.form4_adapter import parse_form4_xml
from alpha_os.core.enums import InstitutionalClassification
from alpha_os.core.models import (
    Form4Transaction,
    Form13FPosition,
    InstitutionalSignal,
    OptionsFlowObservation,
    RelativeVolumeObservation,
)
from alpha_os.core.enums import InstitutionalDataStatus
from alpha_os.engine.institutional_engine import (
    FORM13F_NEW_POSITION_IMPACT,
    _QUARTERLY_MULTIPLIER,
    InstitutionalEngine,
)

FORM4_XML_MIXED_CODES = b"""<?xml version="1.0"?>
<ownershipDocument>
    <reportingOwner>
        <reportingOwnerId><rptOwnerName>Test Insider</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship><isOfficer>true</isOfficer><isDirector>false</isDirector></reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <transactionDate><value>2026-06-01</value></transactionDate>
            <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
            <transactionAmounts>
                <transactionShares><value>1000</value></transactionShares>
                <transactionPricePerShare><value>50.0</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
        </nonDerivativeTransaction>
        <nonDerivativeTransaction>
            <transactionDate><value>2026-06-02</value></transactionDate>
            <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
            <transactionAmounts>
                <transactionShares><value>5000</value></transactionShares>
                <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
        </nonDerivativeTransaction>
        <nonDerivativeTransaction>
            <transactionDate><value>2026-06-03</value></transactionDate>
            <transactionCoding><transactionCode>F</transactionCode></transactionCoding>
            <transactionAmounts>
                <transactionShares><value>200</value></transactionShares>
                <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
        </nonDerivativeTransaction>
        <nonDerivativeTransaction>
            <transactionDate><value>2026-06-04</value></transactionDate>
            <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
            <transactionAmounts>
                <transactionShares><value>300</value></transactionShares>
                <transactionPricePerShare><value>52.0</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
        </nonDerivativeTransaction>
    </nonDerivativeTable>
</ownershipDocument>
"""


def test_form4_parser_only_keeps_open_market_purchase_and_sale():
    """Sección 8: Form 4 debe diferenciar compra/venta de ejercicio y otros
    códigos administrativos — M (ejercicio) y F (retención fiscal) deben
    descartarse, solo P y S sobreviven."""
    transactions = parse_form4_xml(FORM4_XML_MIXED_CODES, "TEST", "2026-06-05")
    codes = sorted(t.transaction_code for t in transactions)
    assert codes == ["P", "S"]
    assert len(transactions) == 2


class _FakeMarketData:
    """No se usa directamente; RelativeVolumeAdapter real necesita un
    MarketDataAdapter, pero para los tests inyectamos la observación
    directamente vía un adapter falso más simple (ver _FakeRelativeVolume)."""


class _FakeRelativeVolume:
    def __init__(self, observation):
        self._observation = observation

    def get_observation(self, ticker):
        return self._observation


class _FakeOptionsFlow:
    def __init__(self, observation):
        self._observation = observation

    def get_observation(self, ticker):
        return self._observation


class _FakeForm4:
    def __init__(self, transactions):
        self._transactions = transactions

    def get_recent_transactions(self, ticker, limit=10):
        return self._transactions


class _FakeForm13F:
    def __init__(self, positions):
        self._positions = positions

    def get_positions(self, ticker, lookback_quarters=2):
        return self._positions


class _FailingAdapter:
    """Simula una fuente cuya llamada real falla — los adapters reales ya
    atrapan la excepción y devuelven vacío/None; este fake reproduce
    exactamente ese contrato para probar que el motor no se cae."""

    def get_observation(self, ticker):
        return None

    def get_recent_transactions(self, ticker, limit=10):
        return []

    def get_positions(self, ticker, lookback_quarters=2):
        return []


def _build_engine(
    relative_volume=None, options_flow=None, form4_transactions=None, form13f_positions=None
):
    return InstitutionalEngine(
        relative_volume=_FakeRelativeVolume(relative_volume),
        options_flow=_FakeOptionsFlow(options_flow),
        form4=_FakeForm4(form4_transactions or []),
        form13f=_FakeForm13F(form13f_positions or []),
    )


def test_high_volume_alone_does_not_imply_direction():
    """Principio obligatorio del spec: no inferir compra/venta institucional
    únicamente porque aumentó el volumen."""
    engine = _build_engine(
        relative_volume=RelativeVolumeObservation(ticker="TEST", volume_zscore=3.0)
    )
    assessment = engine.assess("TEST")
    assert assessment.classification in (
        InstitutionalClassification.NEUTRAL,
        InstitutionalClassification.INSUFFICIENT_DATA,
    )
    assert assessment.score == 0.0
    assert all(s.impact == 0.0 for s in assessment.signals)


def test_missing_sources_return_insufficient_data():
    engine = _build_engine()
    assessment = engine.assess("TEST")
    assert assessment.classification == InstitutionalClassification.INSUFFICIENT_DATA
    assert assessment.confidence == 0.0
    assert assessment.score == 0.0
    assert assessment.data_freshness == "none"


def test_adapter_failure_does_not_crash_engine():
    """Sección 8: una falla temporal de una API no debe derribar el motor."""
    engine = InstitutionalEngine(
        relative_volume=_FailingAdapter(),
        options_flow=_FailingAdapter(),
        form4=_FailingAdapter(),
        form13f=_FailingAdapter(),
    )
    assessment = engine.assess("TEST")
    assert assessment.classification == InstitutionalClassification.INSUFFICIENT_DATA



# El motor calcula antigüedad con datetime.utcnow().date() — usar la misma
# referencia aquí evita off-by-one si la zona horaria local del test difiere
# de UTC (p. ej. de noche en América ya es "mañana" en UTC).
_TODAY_UTC = datetime.utcnow().date()


def test_old_form4_purchase_outside_lookback_is_excluded():
    """Una compra reportada hace mucho tiempo no debe tratarse como
    posicionamiento vigente (spec sección 5: antigüedad penaliza)."""
    old_tx = Form4Transaction(
        ticker="TEST",
        insider_name="Old Insider",
        is_officer=True,
        is_director=False,
        transaction_code="P",
        acquired_disposed="A",
        shares=1000,
        price_per_share=10.0,
        transaction_date=_TODAY_UTC - timedelta(days=200),
        filed_date=_TODAY_UTC - timedelta(days=200),
    )
    engine = _build_engine(form4_transactions=[old_tx])
    assessment = engine.assess("TEST")
    assert assessment.classification == InstitutionalClassification.INSUFFICIENT_DATA


def test_single_recent_form4_purchase_is_not_enough_for_accumulation():
    """Una sola señal, aunque sea una compra confirmada, no debe bastar para
    clasificar como acumulación — el spec exige convergencia de varias
    señales (ver su propio ejemplo: 3 señales suman a 42, ninguna sola
    alcanza el umbral por sí misma). NEUTRAL con score>0 es el resultado
    correcto, no un bug."""
    recent_tx = Form4Transaction(
        ticker="TEST",
        insider_name="Recent Insider",
        is_officer=True,
        is_director=False,
        transaction_code="P",
        acquired_disposed="A",
        shares=1000,
        price_per_share=10.0,
        transaction_date=_TODAY_UTC - timedelta(days=1),
        filed_date=_TODAY_UTC,
    )
    engine = _build_engine(form4_transactions=[recent_tx])
    assessment = engine.assess("TEST")
    assert assessment.score > 0
    assert assessment.classification == InstitutionalClassification.NEUTRAL
    assert assessment.signals[0].status == InstitutionalDataStatus.CONFIRMED


def test_converging_signals_cross_into_moderate_accumulation():
    """Dos señales confirmatorias (compra de insider + actividad inusual de
    calls) sí deben cruzar el umbral — la convergencia es lo que exige
    el spec, no una señal aislada."""
    recent_tx = Form4Transaction(
        ticker="TEST",
        insider_name="Recent Insider",
        is_officer=True,
        is_director=False,
        transaction_code="P",
        acquired_disposed="A",
        shares=1000,
        price_per_share=10.0,
        transaction_date=_TODAY_UTC - timedelta(days=1),
        filed_date=_TODAY_UTC,
    )
    engine = _build_engine(
        form4_transactions=[recent_tx],
        options_flow=OptionsFlowObservation(
            ticker="TEST",
            expiration=_TODAY_UTC,
            call_volume=1000,
            put_volume=100,
            call_open_interest=500,
            put_open_interest=500,
            put_call_volume_ratio=0.1,
            unusual_call_activity=True,
            unusual_put_activity=False,
        ),
    )
    assessment = engine.assess("TEST")
    assert assessment.classification in (
        InstitutionalClassification.MODERATE_ACCUMULATION,
        InstitutionalClassification.STRONG_ACCUMULATION,
    )


def test_contradictory_signals_reduce_confidence():
    """Sección 4: contradicciones deben reducir la confianza."""
    now = datetime.utcnow()
    agreeing_signals = [
        InstitutionalSignal(
            signal="form4_purchase", impact=20.0, status=InstitutionalDataStatus.CONFIRMED,
            source="test", data_date=now, published_date=now, reliability=0.75, description="x",
        ),
        InstitutionalSignal(
            signal="unusual_call_activity", impact=18.0, status=InstitutionalDataStatus.PROXY,
            source="test", data_date=now, published_date=now, reliability=0.45, description="x",
        ),
    ]
    contradicting_signals = agreeing_signals + [
        InstitutionalSignal(
            signal="unusual_put_activity", impact=-18.0, status=InstitutionalDataStatus.PROXY,
            source="test", data_date=now, published_date=now, reliability=0.45, description="x",
        ),
    ]

    engine = _build_engine()
    agreeing_assessment = engine._build_assessment("TEST", agreeing_signals)
    contradicting_assessment = engine._build_assessment("TEST", contradicting_signals)

    assert contradicting_assessment.confidence < agreeing_assessment.confidence


def test_form13f_single_quarter_gives_no_signal():
    """Con un solo trimestre no hay con qué comparar — no se debe inventar
    "posición nueva" cuando en realidad solo falta el dato del trimestre
    anterior (spec: nunca inventar dirección para completar el score)."""
    engine = _build_engine(
        form13f_positions=[
            Form13FPosition(
                manager_name="Test Capital",
                manager_cik="0000000001",
                ticker="TEST",
                shares=1000,
                value_usd=50000,
                report_period_end=_TODAY_UTC,
                filed_date=_TODAY_UTC,
            )
        ]
    )
    assessment = engine.assess("TEST")
    assert assessment.classification == InstitutionalClassification.INSUFFICIENT_DATA


def test_form13f_new_position_detected():
    engine = _build_engine(
        form13f_positions=[
            Form13FPosition(
                manager_name="Test Capital", manager_cik="0000000001", ticker="TEST",
                shares=0, value_usd=0,
                report_period_end=_TODAY_UTC - timedelta(days=90), filed_date=_TODAY_UTC - timedelta(days=80),
            ),
            Form13FPosition(
                manager_name="Test Capital", manager_cik="0000000001", ticker="TEST",
                shares=10000, value_usd=500000,
                report_period_end=_TODAY_UTC, filed_date=_TODAY_UTC,
            ),
        ]
    )
    assessment = engine.assess("TEST")
    matching = [s for s in assessment.signals if s.signal == "form13f_new_position"]
    assert len(matching) == 1
    assert matching[0].impact > 0


def test_form13f_exit_detected():
    engine = _build_engine(
        form13f_positions=[
            Form13FPosition(
                manager_name="Test Capital", manager_cik="0000000001", ticker="TEST",
                shares=10000, value_usd=500000,
                report_period_end=_TODAY_UTC - timedelta(days=90), filed_date=_TODAY_UTC - timedelta(days=80),
            ),
            Form13FPosition(
                manager_name="Test Capital", manager_cik="0000000001", ticker="TEST",
                shares=0, value_usd=0,
                report_period_end=_TODAY_UTC, filed_date=_TODAY_UTC,
            ),
        ]
    )
    assessment = engine.assess("TEST")
    matching = [s for s in assessment.signals if s.signal == "form13f_exit"]
    assert len(matching) == 1
    assert matching[0].impact < 0


def test_form13f_never_treated_as_real_time():
    """Sección 5: datos trimestrales como 13F nunca se tratan como
    posicionamiento actual, sin importar qué tan reciente sea el filing."""
    engine = _build_engine(
        form13f_positions=[
            Form13FPosition(
                manager_name="Test Capital", manager_cik="0000000001", ticker="TEST",
                shares=0, value_usd=0,
                report_period_end=_TODAY_UTC - timedelta(days=90), filed_date=_TODAY_UTC - timedelta(days=1),
            ),
            Form13FPosition(
                manager_name="Test Capital", manager_cik="0000000001", ticker="TEST",
                shares=10000, value_usd=500000,
                report_period_end=_TODAY_UTC, filed_date=_TODAY_UTC,  # filed hoy mismo
            ),
        ]
    )
    assessment = engine.assess("TEST")
    signal = next(s for s in assessment.signals if s.signal == "form13f_new_position")
    assert signal.impact == FORM13F_NEW_POSITION_IMPACT * _QUARTERLY_MULTIPLIER
    assert signal.is_quarterly is True


def test_unusual_options_activity_is_proxy_not_confirmed():
    engine = _build_engine(
        options_flow=OptionsFlowObservation(
            ticker="TEST",
            expiration=date.today(),
            call_volume=1000,
            put_volume=100,
            call_open_interest=500,
            put_open_interest=500,
            put_call_volume_ratio=0.1,
            unusual_call_activity=True,
            unusual_put_activity=False,
        )
    )
    assessment = engine.assess("TEST")
    call_signals = [s for s in assessment.signals if s.signal == "unusual_call_activity"]
    assert len(call_signals) == 1
    assert call_signals[0].status == InstitutionalDataStatus.PROXY
