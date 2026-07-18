import yfinance as yf

from alpha_os.adapters.base import FundamentalDataAdapter
from alpha_os.core.models import FundamentalSnapshot


class YFinanceFundamentalAdapter(FundamentalDataAdapter):
    """Fuente gratuita sin API key. `debt_to_equity` se expone tal como lo
    entrega yfinance sin reescalar — su convención de unidades no es
    consistente entre tickers, así que se trata como informativo y no se usa
    todavía para puntuar convicción."""

    def get_snapshot(self, ticker: str) -> FundamentalSnapshot:
        try:
            info = yf.Ticker(ticker).get_info()
        except Exception:
            return FundamentalSnapshot(ticker=ticker)

        return FundamentalSnapshot(
            ticker=ticker,
            revenue_growth_yoy=info.get("revenueGrowth"),
            gross_margin=info.get("grossMargins"),
            net_margin=info.get("profitMargins"),
            debt_to_equity=info.get("debtToEquity"),
            free_cash_flow=info.get("freeCashflow"),
            pe_ratio=info.get("trailingPE"),
            ev_to_ebitda=info.get("enterpriseToEbitda"),
        )
