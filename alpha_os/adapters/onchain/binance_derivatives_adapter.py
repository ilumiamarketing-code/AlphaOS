import requests

from alpha_os.core.models import DerivativesSnapshot

BASE_URL = "https://fapi.binance.com"


class BinanceDerivativesAdapter:
    """Binance Futures API pública, gratis y sin key (endpoints de mercado,
    no de cuenta). Cualquier fallo de red devuelve un snapshot vacío en vez
    de propagar la excepción."""

    def get_snapshot(self, symbol: str) -> DerivativesSnapshot:
        funding_rate = self._get_funding_rate(symbol)
        open_interest = self._get_open_interest(symbol)
        long_ratio, short_ratio, ls_ratio = self._get_long_short_ratio(symbol)
        return DerivativesSnapshot(
            symbol=symbol,
            funding_rate=funding_rate,
            open_interest=open_interest,
            long_account_ratio=long_ratio,
            short_account_ratio=short_ratio,
            long_short_ratio=ls_ratio,
        )

    def _get_funding_rate(self, symbol: str) -> float | None:
        try:
            response = requests.get(
                f"{BASE_URL}/fapi/v1/premiumIndex", params={"symbol": symbol}, timeout=10
            )
            response.raise_for_status()
            return float(response.json()["lastFundingRate"])
        except (requests.RequestException, KeyError, ValueError):
            return None

    def _get_open_interest(self, symbol: str) -> float | None:
        try:
            response = requests.get(
                f"{BASE_URL}/fapi/v1/openInterest", params={"symbol": symbol}, timeout=10
            )
            response.raise_for_status()
            return float(response.json()["openInterest"])
        except (requests.RequestException, KeyError, ValueError):
            return None

    def _get_long_short_ratio(
        self, symbol: str
    ) -> tuple[float | None, float | None, float | None]:
        try:
            response = requests.get(
                f"{BASE_URL}/futures/data/globalLongShortAccountRatio",
                params={"symbol": symbol, "period": "1d", "limit": 1},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if not data:
                return None, None, None
            latest = data[-1]
            return (
                float(latest["longAccount"]),
                float(latest["shortAccount"]),
                float(latest["longShortRatio"]),
            )
        except (requests.RequestException, KeyError, ValueError, IndexError):
            return None, None, None
