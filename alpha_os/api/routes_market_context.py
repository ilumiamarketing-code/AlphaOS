from fastapi import APIRouter, Depends, Query

from alpha_os.api.deps import get_cross_asset_correlation_adapter, get_market_regime_engine
from alpha_os.core.models import CrossAssetCorrelation, MarketRegimeAssessment
from alpha_os.engine.market_regime_engine import MarketRegimeEngine
from alpha_os.adapters.market_data.cross_asset_correlation_adapter import (
    CrossAssetCorrelationAdapter,
)

router = APIRouter(prefix="/market-context", tags=["market-context"])

DEFAULT_CORRELATION_TICKERS = ["BTC-USD", "ETH-USD", "^GSPC", "^IXIC", "GC=F", "DX-Y.NYB"]


@router.get("/regime", response_model=MarketRegimeAssessment)
def get_regime(engine: MarketRegimeEngine = Depends(get_market_regime_engine)):
    """Market Regime Intelligence — capa de contexto, no genera señales de
    compra/venta por sí misma."""
    return engine.assess()


@router.get("/correlations", response_model=list[CrossAssetCorrelation])
def get_correlations(
    tickers: list[str] = Query(default=DEFAULT_CORRELATION_TICKERS),
    lookback: str = "3mo",
    adapter: CrossAssetCorrelationAdapter = Depends(get_cross_asset_correlation_adapter),
):
    return adapter.get_correlations(tickers, lookback=lookback)
