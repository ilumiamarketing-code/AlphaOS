from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from alpha_os.core.enums import (
    AlertLevel,
    AssetClass,
    EvidenceType,
    InstitutionalClassification,
    InstitutionalDataStatus,
    InvestorProfile,
    LiquidityRegime,
    OperationSide,
    PositionStatus,
    RiskLevel,
    RiskRegime,
    SourceTier,
    TimeHorizon,
    TrendRegime,
)


class Evidence(BaseModel):
    """Un dato individual citado en una señal o alerta, con su procedencia."""

    claim: str
    source_name: str
    source_tier: SourceTier
    evidence_type: EvidenceType
    url: str | None = None
    observed_at: datetime = Field(default_factory=datetime.utcnow)


class ConvictionFactor(BaseModel):
    """Un componente del score de convicción (motor de convicción)."""

    label: str
    weight_pct: float  # puede ser negativo (factor en contra)
    rationale: str
    evidence: list[Evidence] = Field(default_factory=list)


class Signal(BaseModel):
    """Ficha técnica de una señal, spec sección 3-5."""

    ticker: str
    asset_class: AssetClass
    direction: Literal["long", "short"]
    price: float
    conviction_score: float = Field(ge=0, le=100)
    factors: list[ConvictionFactor] = Field(default_factory=list)
    confidence_level: float = Field(ge=0, le=100)
    time_horizon: TimeHorizon
    risk_level: RiskLevel
    recommended_investor_profile: InvestorProfile
    suggested_entry: float | None = None
    stop_loss: float | None = None
    take_profit_targets: list[float] = Field(default_factory=list)
    risk_reward_ratio: float | None = None
    rationale: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    upcoming_catalysts: list[str] = Field(default_factory=list)
    has_contradictions: bool = False


class FundamentalSnapshot(BaseModel):
    ticker: str
    revenue_growth_yoy: float | None = None
    gross_margin: float | None = None
    net_margin: float | None = None
    debt_to_equity: float | None = None
    free_cash_flow: float | None = None
    pe_ratio: float | None = None
    ev_to_ebitda: float | None = None

    def has_data(self) -> bool:
        return any(
            v is not None
            for v in (
                self.revenue_growth_yoy,
                self.gross_margin,
                self.net_margin,
                self.debt_to_equity,
                self.free_cash_flow,
                self.pe_ratio,
                self.ev_to_ebitda,
            )
        )


class MacroSnapshot(BaseModel):
    fed_funds_rate: float | None = None
    cpi_yoy: float | None = None
    global_liquidity_trend: Literal["expanding", "contracting", "stable"] | None = None
    next_macro_events: list[str] = Field(default_factory=list)

    def has_data(self) -> bool:
        return self.fed_funds_rate is not None or self.cpi_yoy is not None


class SentimentSnapshot(BaseModel):
    ticker: str
    score: float | None = None  # -1 (muy negativo) a +1 (muy positivo)
    volume_mentions: int | None = None
    supporting_evidence: list[Evidence] = Field(default_factory=list)


class Anomaly(BaseModel):
    """Comportamiento fuera de patrón detectado sin que exista señal de trading."""

    ticker: str
    description: str
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    evidence: list[Evidence] = Field(default_factory=list)


class OperationEntry(BaseModel):
    """Registro de la operación ejecutada por el usuario (Módulo 10, sección 1)."""

    ticker: str
    asset_class: AssetClass
    side: OperationSide
    broker: str
    executed_at: datetime
    entry_price: float
    quantity: float
    capital_invested: float
    commission_paid: float = 0.0
    expected_horizon: TimeHorizon
    assumed_risk: RiskLevel
    original_thesis: str
    entry_reasons: list[str] = Field(default_factory=list)
    original_signal: Signal | None = None
    sector: str | None = None
    country: str | None = None


class RiskParameters(BaseModel):
    """Administración dinámica del riesgo, sección 5."""

    stop_loss: float
    take_profit: float | None = None
    trailing_stop_pct: float | None = None
    risk_reward_ratio: float | None = None
    max_drawdown_pct: float | None = None


class PositionAlert(BaseModel):
    """Alerta inteligente emitida durante el ciclo de vida de una posición."""

    level: AlertLevel
    reason: str
    evidence: list[Evidence] = Field(default_factory=list)
    confidence_level: float = Field(ge=0, le=100)
    updated_risk: RiskLevel
    thesis_change: str
    issued_at: datetime = Field(default_factory=datetime.utcnow)


class ThesisReassessment(BaseModel):
    """Resultado de recalcular la tesis original ante nueva información (sección 3)."""

    still_valid: bool
    success_probability_delta: float  # +/- respecto a la última evaluación
    what_changed: str
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)


class Position(BaseModel):
    """Una operación confirmada, convertida en posición activa (Módulo 10)."""

    id: str
    entry: OperationEntry
    status: PositionStatus = PositionStatus.ACTIVE
    risk_parameters: RiskParameters
    alerts: list[PositionAlert] = Field(default_factory=list)
    thesis_history: list[ThesisReassessment] = Field(default_factory=list)
    current_price: float | None = None
    max_favorable_excursion: float | None = None  # máximo beneficio flotante
    max_adverse_excursion: float | None = None  # máxima pérdida flotante
    closed_at: datetime | None = None
    exit_price: float | None = None


class ExposureBreakdown(BaseModel):
    by_asset: dict[str, float] = Field(default_factory=dict)
    by_sector: dict[str, float] = Field(default_factory=dict)
    by_country: dict[str, float] = Field(default_factory=dict)
    by_asset_class: dict[str, float] = Field(default_factory=dict)


class PortfolioRiskReport(BaseModel):
    """Salida de la administración de portafolio, sección 6."""

    exposure: ExposureBreakdown
    overexposure_flags: list[str] = Field(default_factory=list)
    duplicated_risk_flags: list[str] = Field(default_factory=list)
    high_correlation_pairs: list[tuple[str, str, float]] = Field(default_factory=list)
    systemic_risk_notes: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class PostMortem(BaseModel):
    """Análisis al cerrar una posición, sección 8."""

    what_went_well: str
    what_went_wrong: str
    decisive_information: str
    signals_that_anticipated_move: list[str] = Field(default_factory=list)
    irrelevant_indicators: list[str] = Field(default_factory=list)
    lessons_learned: str


class RelativeVolumeObservation(BaseModel):
    """Dato crudo, sin dirección — el volumen alto por sí solo nunca implica
    compra o venta institucional (spec módulo institucional, sección 1)."""

    ticker: str
    volume_zscore: float
    as_of: datetime = Field(default_factory=datetime.utcnow)


class OptionsFlowObservation(BaseModel):
    """Snapshot del vencimiento más próximo. Sin historial de baseline, así
    que la actividad "inusual" es una heurística de un solo corte, no una
    comparación contra su propio promedio histórico."""

    ticker: str
    expiration: date
    call_volume: int
    put_volume: int
    call_open_interest: int
    put_open_interest: int
    put_call_volume_ratio: float | None
    unusual_call_activity: bool
    unusual_put_activity: bool
    as_of: datetime = Field(default_factory=datetime.utcnow)


class Form4Transaction(BaseModel):
    """Una transacción individual reportada en un Form 4 de SEC EDGAR."""

    ticker: str
    insider_name: str
    is_officer: bool
    is_director: bool
    transaction_code: str  # código SEC crudo: P, S, A, M, F, G, C, etc.
    acquired_disposed: str  # "A" adquirido o "D" dispuesto
    shares: float
    price_per_share: float | None
    transaction_date: date
    filed_date: date
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)


class Form13FPosition(BaseModel):
    """Posición de un gestor institucional en un trimestre dado. `shares=0`
    significa "presentó 13F ese trimestre pero sin holding en este emisor" —
    distinto de no tener dato del todo (eso simplemente no genera esta
    entrada). 13F reporta por CUSIP, no por ticker, así que el match es por
    nombre de emisor normalizado y puede tener falsos negativos."""

    manager_name: str
    manager_cik: str
    ticker: str
    shares: float
    value_usd: float
    report_period_end: date
    filed_date: date
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)


class InstitutionalSignal(BaseModel):
    """Una observación individual ya interpretada (impacto con signo,
    status de confiabilidad, fechas de dato/publicación/consulta) — spec
    módulo institucional, secciones 4-5."""

    signal: str
    impact: float  # contribución con signo al score, no acotada aún a -100..100
    status: InstitutionalDataStatus
    source: str
    data_date: datetime
    published_date: datetime | None
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    reliability: float = Field(ge=0, le=1)
    description: str
    is_quarterly: bool = False  # 13F-like: nunca tratar como posición actual


class InstitutionalAssessment(BaseModel):
    """Resultado agregado del motor institucional para un ticker."""

    ticker: str
    score: float = Field(ge=-100, le=100)
    classification: InstitutionalClassification
    confidence: float = Field(ge=0, le=1)
    signals: list[InstitutionalSignal] = Field(default_factory=list)
    data_freshness: Literal["real_time", "recent", "aging", "stale", "mixed", "none"]
    rationale: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    @computed_field
    @property
    def evidence(self) -> list[InstitutionalSignal]:
        if self.score > 0:
            return [s for s in self.signals if s.impact > 0]
        if self.score < 0:
            return [s for s in self.signals if s.impact < 0]
        return []

    @computed_field
    @property
    def contradictions(self) -> list[InstitutionalSignal]:
        if self.score > 0:
            return [s for s in self.signals if s.impact < 0]
        if self.score < 0:
            return [s for s in self.signals if s.impact > 0]
        return []


class DerivativesSnapshot(BaseModel):
    """Binance futuros perpetuos, gratis y sin key. No interpreta — solo
    reporta; la lectura (exceso de apalancamiento, riesgo de squeeze) la
    hace analysis/derivatives.py."""

    symbol: str
    funding_rate: float | None = None
    open_interest: float | None = None
    long_account_ratio: float | None = None
    short_account_ratio: float | None = None
    long_short_ratio: float | None = None
    as_of: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return any(v is not None for v in (self.funding_rate, self.open_interest, self.long_short_ratio))


class StablecoinSnapshot(BaseModel):
    """CoinGecko, gratis y sin key. `market_cap_change_pct` es un proxy de
    cambio de supply (stablecoins ~$1, así que cap ≈ supply), no un dato de
    mint/burn directo — no hay fuente gratis para eso."""

    symbol: str
    circulating_supply: float | None = None
    market_cap_usd: float | None = None
    market_cap_change_24h_pct: float | None = None
    supply_change_7d_pct: float | None = None
    dominance_pct: float | None = None
    as_of: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return self.circulating_supply is not None


class CrossAssetCorrelation(BaseModel):
    asset_a: str
    asset_b: str
    correlation: float
    window_days: int
    as_of: datetime = Field(default_factory=datetime.utcnow)


class MarketRegimeAssessment(BaseModel):
    """Capa de contexto (no genera señales de compra/venta por sí misma):
    identifica el régimen del mercado y los multiplicadores de peso que
    deben aplicarse a los factores del motor de señales."""

    trend_regime: TrendRegime
    risk_regime: RiskRegime
    liquidity_regime: LiquidityRegime
    high_volatility_event: bool
    confidence: float = Field(ge=0, le=1)
    justification: list[str] = Field(default_factory=list)
    weight_adjustments: dict[str, float] = Field(default_factory=dict)
    reference_index: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class JournalEntry(BaseModel):
    """Diario automático por operación, sección 7."""

    position_id: str
    entry_reason: str
    changes_during_operation: list[str] = Field(default_factory=list)
    alerts_issued: list[PositionAlert] = Field(default_factory=list)
    actions_taken: list[str] = Field(default_factory=list)
    final_result: str | None = None
    profitability_pct: float | None = None
    max_gain_reached: float | None = None
    max_floating_loss: float | None = None
    time_in_market: str | None = None
    post_mortem: PostMortem | None = None


class WalletTransaction(BaseModel):
    """Una transacción individual de una wallet consultada. `direction` es
    el efecto neto sobre el balance de la wallet consultada, no una
    interpretación de compra/venta (spec: nunca interpretar automáticamente
    una transferencia como decisión de trading)."""

    tx_hash: str
    timestamp: datetime
    amount: float
    direction: Literal["in", "out"]


class WalletFlowSnapshot(BaseModel):
    """Flujo de una wallet consultada. La identidad (label/source/confidence)
    la declara siempre quien hace la consulta — este sistema nunca asume
    automáticamente que una dirección pertenece a un exchange/fondo/etc."""

    address: str
    chain: Literal["bitcoin", "ethereum"]
    label: str
    label_source: str
    label_confidence: float = Field(ge=0, le=1)
    lookback_days: int
    effective_lookback_days: int  # puede ser menor al pedido si la wallet es muy activa (límite de páginas consultadas)
    total_inflow: float
    total_outflow: float
    net_flow: float
    daily_net_flows: list[float] = Field(default_factory=list)
    average_daily_net_flow: float | None = None
    stddev_daily_net_flow: float | None = None
    latest_day_net_flow: float | None = None
    is_anomalous: bool = False
    anomaly_description: str | None = None
    large_transactions: list[WalletTransaction] = Field(default_factory=list)
    as_of: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return self.total_inflow > 0 or self.total_outflow > 0


class TokenTransferSummary(BaseModel):
    """Agregado de transferencias ERC-20 de un solo contrato de token dentro
    de la ventana consultada — separado de WalletTransaction porque un
    token no tiene el mismo "amount" universal que ETH nativo (cada
    contrato define sus propios decimales y símbolo)."""

    token_symbol: str
    token_contract: str
    token_decimals: int
    inflow: float
    outflow: float
    net_flow: float
    tx_count: int


class TokenFlowSnapshot(BaseModel):
    """Flujo de tokens ERC-20 de una wallet Ethereum (endpoint `tokentx` de
    Etherscan) — independiente de WalletFlowSnapshot, que solo cubre ETH
    nativo (`txlist`). Misma política de identidad: label/source/confidence
    los declara siempre quien llama, nunca se infiere automáticamente."""

    address: str
    label: str
    label_source: str
    label_confidence: float = Field(ge=0, le=1)
    lookback_days: int
    effective_lookback_days: int
    tokens: list[TokenTransferSummary] = Field(default_factory=list)
    as_of: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return len(self.tokens) > 0


class NetworkHealthSnapshot(BaseModel):
    """Salud de red on-chain (BTC vía blockchain.info charts, gratis)."""

    chain: Literal["bitcoin", "ethereum"]
    hash_rate: float | None = None
    tx_count_24h: float | None = None
    avg_fee_usd: float | None = None
    hash_rate_change_30d_pct: float | None = None
    tx_count_change_30d_pct: float | None = None
    as_of: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return any(v is not None for v in (self.hash_rate, self.tx_count_24h, self.avg_fee_usd))


class DeFiTVLSnapshot(BaseModel):
    """TVL de una chain vía DeFiLlama, gratis y sin key."""

    chain: str
    tvl_usd: float | None = None
    tvl_change_7d_pct: float | None = None
    as_of: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return self.tvl_usd is not None


class HalvingEstimate(BaseModel):
    """Determinístico a partir del protocolo (cada 210,000 bloques) — la
    fecha exacta varía con el hashrate real, por eso es una estimación."""

    current_block_height: int
    next_halving_block: int
    blocks_remaining: int
    estimated_date: datetime
    estimated_days_remaining: float


class GitHubActivitySnapshot(BaseModel):
    """Actividad de desarrollo de un repo declarado por quien consulta — no
    se preselecciona qué proyecto "representa" una narrativa."""

    repo: str
    stars: int | None = None
    open_issues: int | None = None
    commits_recent: int | None = None
    commits_baseline_avg: float | None = None
    commit_activity_ratio: float | None = None  # recent / baseline
    lookback_days: int
    as_of: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return self.stars is not None


class MediumTagSnapshot(BaseModel):
    """Volumen y sentimiento de artículos recientes de un tag de Medium.
    RSS solo expone los últimos ~10-25 artículos, sin control de ventana."""

    tag: str
    article_count: int
    average_sentiment: float | None = None
    articles: list[Evidence] = Field(default_factory=list)
    as_of: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return self.article_count > 0


class RedditSubredditSnapshot(BaseModel):
    """Volumen, score promedio y sentimiento de posts recientes de un
    subreddit declarado por quien consulta."""

    subreddit: str
    post_count: int
    average_score: float | None = None
    average_sentiment: float | None = None
    posts: list[Evidence] = Field(default_factory=list)
    lookback_days: int
    as_of: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return self.post_count > 0


class GovernanceProposal(BaseModel):
    """Una propuesta de gobernanza de un espacio DAO en Snapshot."""

    proposal_id: str
    space: str
    title: str
    state: str  # "active" | "closed" | "pending"
    start: datetime
    end: datetime
    url: str | None = None


class GovernanceSnapshot(BaseModel):
    """El espacio (DAO) lo declara quien consulta — no se preselecciona
    qué DAO "importa" para ninguna narrativa."""

    space: str
    proposals: list[GovernanceProposal] = Field(default_factory=list)
    as_of: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return len(self.proposals) > 0


class CalendarEvent(BaseModel):
    """Un evento individual de CoinMarketCal API v2 (unlock, fork, listing,
    etc.). `date` es para ordenar/filtrar — cuando `is_estimated=True` es
    una fecha límite/ventana, no un dato literal; para mostrar al usuario
    usar siempre `displayed_date`, nunca `date` directo (regla explícita de
    la doc de CoinMarketCal)."""

    event_id: str
    title: str
    coin_symbols: list[str] = Field(default_factory=list)
    date: datetime
    displayed_date: str
    is_estimated: bool
    category: str | None = None
    source_url: str | None = None
    impact: str | float | None = None  # null en Free/Standard, string en Pro, float en Elite+


class CoinCalendarSnapshot(BaseModel):
    coin_slug: str
    events: list[CalendarEvent] = Field(default_factory=list)
    as_of: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return len(self.events) > 0


class ProtocolTVLSnapshot(BaseModel):
    """TVL de un protocolo DeFi específico (no una chain completa) vía
    DeFiLlama, gratis y sin key."""

    protocol_slug: str
    name: str | None = None
    category: str | None = None
    tvl_usd: float | None = None
    as_of: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return self.tvl_usd is not None


class DexVolumeSnapshot(BaseModel):
    """Volumen agregado de exchanges descentralizados de una chain vía
    DeFiLlama, gratis y sin key."""

    chain: str
    volume_24h_usd: float | None = None
    volume_7d_usd: float | None = None
    change_24h_pct: float | None = None
    as_of: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return self.volume_24h_usd is not None


class FeesRevenueSnapshot(BaseModel):
    """Fees/revenue agregados de protocolos de una chain vía DeFiLlama,
    gratis y sin key."""

    chain: str
    fees_24h_usd: float | None = None
    fees_7d_usd: float | None = None
    change_24h_pct: float | None = None
    as_of: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return self.fees_24h_usd is not None


class FactorPerformance(BaseModel):
    """Desempeño real de un factor a través de posiciones ya cerradas.
    `has_sufficient_sample` en False significa que la muestra es
    demasiado pequeña para sugerir nada responsablemente — no se debe
    ajustar ningún peso sin esto en True."""

    factor_label: str
    occurrences_supporting: int
    occurrences_contradicting: int
    avg_profitability_when_supporting: float | None = None
    win_rate_when_supporting: float | None = None
    has_sufficient_sample: bool = False


class LearningReport(BaseModel):
    """Salida del módulo de aprendizaje continuo (spec sección 8). Nunca
    aplica cambios automáticamente a DEFAULT_FACTOR_WEIGHTS — solo reporta
    para revisión humana, y solo con datos ya realizados (posiciones
    cerradas), nunca información futura."""

    total_closed_positions: int
    positions_with_signal_data: int
    factor_performance: list[FactorPerformance] = Field(default_factory=list)
    rationale: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return self.positions_with_signal_data > 0
