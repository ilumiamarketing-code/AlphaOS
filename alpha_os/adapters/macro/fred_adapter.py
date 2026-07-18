import requests

from alpha_os.adapters.base import MacroDataAdapter
from alpha_os.config import settings
from alpha_os.core.models import MacroSnapshot

FRED_ENDPOINT = "https://api.stlouisfed.org/fred/series/observations"

# Umbral para clasificar la tendencia de tasas como cambio real vs. ruido de
# redondeo (FEDFUNDS se reporta con un decimal).
RATE_TREND_THRESHOLD = 0.1


def _fetch_observations(series_id: str, limit: int) -> list[tuple[str, float]]:
    try:
        response = requests.get(
            FRED_ENDPOINT,
            params={
                "series_id": series_id,
                "api_key": settings.fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            },
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException:
        return []

    observations = []
    for obs in response.json().get("observations", []):
        value = obs.get("value")
        if value in (None, "."):
            continue
        observations.append((obs["date"], float(value)))
    return observations


class FREDMacroAdapter(MacroDataAdapter):
    """Fuente gratuita (Federal Reserve Economic Data, fred.stlouisfed.org).
    Sin API key configurada se comporta como el mock: devuelve un snapshot
    vacío en vez de fallar. FEDFUNDS y CPIAUCSL son series mensuales, así que
    la tendencia de tasas compara el valor actual contra el de ~6 meses
    atrás; el calendario de próximos eventos macro sigue sin fuente."""

    def get_snapshot(self) -> MacroSnapshot:
        if not settings.fred_api_key:
            return MacroSnapshot()

        # Se pide más de lo estrictamente necesario (7 y 13 meses) porque el
        # dato más reciente de una serie a veces llega como "." (preliminar,
        # aún no publicado) y se filtra en _fetch_observations — sin margen,
        # eso deja el conteo justo por debajo de lo necesario.
        fed_funds_obs = _fetch_observations("FEDFUNDS", limit=9)
        fed_funds_rate = fed_funds_obs[0][1] if fed_funds_obs else None

        liquidity_trend = None
        if len(fed_funds_obs) >= 7:
            diff = fed_funds_obs[0][1] - fed_funds_obs[6][1]
            if diff <= -RATE_TREND_THRESHOLD:
                liquidity_trend = "expanding"
            elif diff >= RATE_TREND_THRESHOLD:
                liquidity_trend = "contracting"
            else:
                liquidity_trend = "stable"

        cpi_obs = _fetch_observations("CPIAUCSL", limit=16)
        cpi_yoy = None
        if len(cpi_obs) >= 13 and cpi_obs[12][1] != 0:
            cpi_yoy = cpi_obs[0][1] / cpi_obs[12][1] - 1

        return MacroSnapshot(
            fed_funds_rate=fed_funds_rate,
            cpi_yoy=cpi_yoy,
            global_liquidity_trend=liquidity_trend,
        )
