import requests

from alpha_os.core.models import StablecoinSnapshot

BASE_URL = "https://api.coingecko.com/api/v3"

# CoinGecko usa slugs, no tickers, para sus endpoints por moneda.
COIN_ID_BY_SYMBOL = {
    "USDT": "tether",
    "USDC": "usd-coin",
    "DAI": "dai",
    "FDUSD": "first-digital-usd",
}


class CoinGeckoStablecoinAdapter:
    """CoinGecko API pública, gratis y sin key (rate-limited). No hay mint/
    burn directo en el tier gratuito — se usa el cambio de market cap como
    proxy de cambio de supply, documentado como tal en el modelo."""

    def get_snapshot(self, symbol: str) -> StablecoinSnapshot:
        coin_id = COIN_ID_BY_SYMBOL.get(symbol.upper())
        if not coin_id:
            return StablecoinSnapshot(symbol=symbol)

        try:
            response = requests.get(
                f"{BASE_URL}/coins/{coin_id}",
                params={
                    "localization": "false",
                    "tickers": "false",
                    "market_data": "true",
                    "community_data": "false",
                    "developer_data": "false",
                },
                timeout=15,
            )
            response.raise_for_status()
            market_data = response.json()["market_data"]
        except (requests.RequestException, KeyError, ValueError):
            return StablecoinSnapshot(symbol=symbol)

        supply_change_7d = self._supply_change_7d(coin_id)
        dominance = self._dominance_pct(symbol)

        return StablecoinSnapshot(
            symbol=symbol,
            circulating_supply=market_data.get("circulating_supply"),
            market_cap_usd=(market_data.get("market_cap") or {}).get("usd"),
            market_cap_change_24h_pct=market_data.get("market_cap_change_percentage_24h"),
            supply_change_7d_pct=supply_change_7d,
            dominance_pct=dominance,
        )

    def _supply_change_7d(self, coin_id: str) -> float | None:
        try:
            response = requests.get(
                f"{BASE_URL}/coins/{coin_id}/market_chart",
                params={"vs_currency": "usd", "days": 8},
                timeout=15,
            )
            response.raise_for_status()
            market_caps = response.json()["market_caps"]
        except (requests.RequestException, KeyError, ValueError):
            return None
        if len(market_caps) < 2:
            return None
        oldest, latest = market_caps[0][1], market_caps[-1][1]
        if not oldest:
            return None
        return (latest - oldest) / oldest

    def _dominance_pct(self, symbol: str) -> float | None:
        try:
            response = requests.get(f"{BASE_URL}/global", timeout=15)
            response.raise_for_status()
            percentages = response.json()["data"]["market_cap_percentage"]
        except (requests.RequestException, KeyError, ValueError):
            return None
        return percentages.get(symbol.lower())
