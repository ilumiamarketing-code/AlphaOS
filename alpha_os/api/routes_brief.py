from fastapi import APIRouter, Depends

from alpha_os.adapters.broker.ibkr_adapter import IBKRAdapter
from alpha_os.adapters.news.newsapi_adapter import NewsAPIAdapter
from alpha_os.api.deps import (
    get_ibkr_adapter,
    get_learning_engine,
    get_market_regime_engine,
    get_news_adapter,
    get_position_manager,
    get_signal_engine,
)
from alpha_os.config import settings
from alpha_os.core.enums import OperationSide
from alpha_os.core.models import AlphaBrief, PositionBriefCard
from alpha_os.engine.learning_engine import LearningEngine
from alpha_os.engine.market_regime_engine import MarketRegimeEngine
from alpha_os.engine.signal_engine import SignalEngine
from alpha_os.positions.position_manager import PositionManager

router = APIRouter(prefix="/brief", tags=["brief"])

MAX_OPPORTUNITIES = 5


def _position_card(position, position_manager: PositionManager, signal_engine: SignalEngine) -> PositionBriefCard:
    entry = position.entry
    floating_pnl_pct = None
    if position.current_price is not None:
        direction = 1 if entry.side == OperationSide.BUY else -1
        floating_pnl_pct = direction * (position.current_price - entry.entry_price) / entry.entry_price * 100

    return PositionBriefCard(
        position_id=position.id,
        ticker=entry.ticker,
        side=entry.side.value,
        entry_price=entry.entry_price,
        current_price=position.current_price,
        floating_pnl_pct=floating_pnl_pct,
        thesis=position_manager.reassess_thesis(position.id, signal_engine),
    )


@router.get("", response_model=AlphaBrief)
async def get_alpha_brief(
    signal_engine: SignalEngine = Depends(get_signal_engine),
    market_regime_engine: MarketRegimeEngine = Depends(get_market_regime_engine),
    position_manager: PositionManager = Depends(get_position_manager),
    news: NewsAPIAdapter = Depends(get_news_adapter),
    learning_engine: LearningEngine = Depends(get_learning_engine),
    ibkr: IBKRAdapter = Depends(get_ibkr_adapter),
):
    """Agrega salidas ya existentes de MarketRegimeEngine, PositionManager +
    SignalEngine (reevaluación de tesis), un escaneo del watchlist
    configurado (`settings.watchlist`) ordenado por conviction_score,
    titulares generales de NewsAPI, y el resumen de cuenta real de IBKR (si
    TWS/Gateway está corriendo — si no, `broker_account` queda `None`, igual
    que el resto de fuentes sin conexión). No calcula nada nuevo — es pura
    composición para que la pantalla principal no tenga que hacer 6+
    llamadas por separado. Advertencia de performance: escanea todo el
    watchlist en cada llamada (varias solicitudes de red reales por
    ticker), puede tardar varios segundos."""
    market_regime = market_regime_engine.assess()

    open_positions = [
        _position_card(p, position_manager, signal_engine) for p in position_manager.list_active()
    ]

    opportunities = []
    for ticker, asset_class in settings.watchlist:
        signal = signal_engine.generate_signal(ticker, asset_class)
        if signal is not None:
            opportunities.append(signal)
    opportunities.sort(key=lambda s: s.conviction_score, reverse=True)
    opportunities = opportunities[:MAX_OPPORTUNITIES]

    headlines = news.get_market_headlines(limit=5)
    learning = learning_engine.analyze_factor_performance()

    broker_account = await ibkr.get_account_summary()
    if not broker_account.has_data():
        broker_account = None

    return AlphaBrief(
        market_regime=market_regime,
        broker_account=broker_account,
        open_positions=open_positions,
        opportunities=opportunities,
        headlines=headlines,
        learning=learning,
    )
