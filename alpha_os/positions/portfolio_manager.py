from alpha_os.adapters.market_data.cross_asset_correlation_adapter import (
    CrossAssetCorrelationAdapter,
)
from alpha_os.core.enums import OperationSide, TrendRegime
from alpha_os.core.models import ExposureBreakdown, PortfolioRiskReport
from alpha_os.engine.market_regime_engine import MarketRegimeEngine
from alpha_os.positions.position_manager import PositionManager

# Umbrales simples de concentración; recalibrables según perfil de riesgo.
SINGLE_ASSET_LIMIT_PCT = 25.0
SINGLE_SECTOR_LIMIT_PCT = 40.0
SINGLE_ASSET_CLASS_LIMIT_PCT = 60.0
HIGH_CORRELATION_THRESHOLD = 0.8


class PortfolioManager:
    """Sección 6 del spec: deja de mirar activos individuales y evalúa el
    portafolio completo — multi-activo desde el diseño, ya que
    `OperationEntry.asset_class` distingue equity/crypto/fx/commodity/etf/
    bond y la exposición se agrega también por esa dimensión, no solo por
    ticker/sector/país. La correlación se delega a
    `CrossAssetCorrelationAdapter` (no se duplica esa lógica aquí) — tenía
    un bug real de timezone (cripto en UTC vs. equities en la tz de su
    bolsa) que hacía que ningún par cripto↔tradicional se calculara nunca;
    reusar el adapter ya corregido evita repetir el mismo bug dos veces."""

    def __init__(
        self,
        position_manager: PositionManager,
        correlation_adapter: CrossAssetCorrelationAdapter,
        market_regime_engine: MarketRegimeEngine,
    ):
        self.position_manager = position_manager
        self.correlation_adapter = correlation_adapter
        self.market_regime_engine = market_regime_engine

    def compute_exposure(self) -> ExposureBreakdown:
        positions = self.position_manager.list_active()
        by_asset: dict[str, float] = {}
        by_sector: dict[str, float] = {}
        by_country: dict[str, float] = {}
        by_asset_class: dict[str, float] = {}
        for p in positions:
            by_asset[p.entry.ticker] = by_asset.get(p.entry.ticker, 0.0) + p.entry.capital_invested
            by_asset_class[p.entry.asset_class.value] = (
                by_asset_class.get(p.entry.asset_class.value, 0.0) + p.entry.capital_invested
            )
            if p.entry.sector:
                by_sector[p.entry.sector] = (
                    by_sector.get(p.entry.sector, 0.0) + p.entry.capital_invested
                )
            if p.entry.country:
                by_country[p.entry.country] = (
                    by_country.get(p.entry.country, 0.0) + p.entry.capital_invested
                )
        return ExposureBreakdown(
            by_asset=by_asset, by_sector=by_sector, by_country=by_country, by_asset_class=by_asset_class
        )

    def _concentration_flags(self, exposure: dict[str, float], total: float, limit_pct: float) -> list[str]:
        if total <= 0:
            return []
        return [
            f"{key}: {amount / total * 100:.1f}% del portafolio (límite {limit_pct:.0f}%)"
            for key, amount in exposure.items()
            if amount / total * 100 > limit_pct
        ]

    def _high_correlation_pairs(self, tickers: list[str]) -> list[tuple[str, str, float]]:
        correlations = self.correlation_adapter.get_correlations(tickers)
        return [
            (c.asset_a, c.asset_b, c.correlation)
            for c in correlations
            if abs(c.correlation) >= HIGH_CORRELATION_THRESHOLD
        ]

    def _systemic_risk_notes(self, exposure: ExposureBreakdown, total_capital: float) -> list[str]:
        """Riesgo sistémico por evento macro compartido (pendiente desde el
        diseño inicial) — ahora conectado vía MarketRegimeEngine, que ya
        clasifica tendencia/riesgo/liquidez del mercado en general."""
        if total_capital <= 0:
            return []

        regime = self.market_regime_engine.assess()
        notes = []

        crypto_pct = exposure.by_asset_class.get("crypto", 0.0) / total_capital * 100
        if regime.high_volatility_event and crypto_pct > 30.0:
            notes.append(
                f"Evento de alta volatilidad detectado ({regime.trend_regime.value}) con "
                f"{crypto_pct:.1f}% del portafolio en cripto — activo típicamente más sensible "
                "a eventos de volatilidad que equities/bonos."
            )

        equity_pct = exposure.by_asset_class.get("equity", 0.0) / total_capital * 100
        long_positions = [
            p for p in self.position_manager.list_active() if p.entry.side == OperationSide.BUY
        ]
        net_long_equity_capital = sum(
            p.entry.capital_invested for p in long_positions if p.entry.asset_class.value == "equity"
        )
        net_long_equity_pct = net_long_equity_capital / total_capital * 100
        if (
            regime.trend_regime in (TrendRegime.BEAR_CAPITULATION, TrendRegime.BEAR_DISTRIBUTION)
            and net_long_equity_pct > 40.0
        ):
            notes.append(
                f"Régimen de mercado {regime.trend_regime.value} con {net_long_equity_pct:.1f}% del "
                "portafolio en posiciones largas de equities — exposición direccional alta durante "
                "un contexto bajista general."
            )

        if not notes:
            notes.append(
                f"Sin banderas de riesgo sistémico bajo el régimen actual "
                f"({regime.trend_regime.value}/{regime.risk_regime.value}/{regime.liquidity_regime.value})."
            )
        return notes

    def generate_risk_report(self) -> PortfolioRiskReport:
        exposure = self.compute_exposure()
        total_capital = sum(exposure.by_asset.values())

        overexposure_flags = (
            self._concentration_flags(exposure.by_asset, total_capital, SINGLE_ASSET_LIMIT_PCT)
            + self._concentration_flags(exposure.by_sector, total_capital, SINGLE_SECTOR_LIMIT_PCT)
            + self._concentration_flags(
                exposure.by_asset_class, total_capital, SINGLE_ASSET_CLASS_LIMIT_PCT
            )
        )

        duplicated_risk_flags = [
            f"Sector '{sector}' concentra {amount / total_capital * 100:.1f}% en múltiples posiciones"
            for sector, amount in exposure.by_sector.items()
            if total_capital > 0 and amount / total_capital * 100 > SINGLE_SECTOR_LIMIT_PCT
        ]

        high_correlation_pairs = self._high_correlation_pairs(list(exposure.by_asset.keys()))
        systemic_risk_notes = self._systemic_risk_notes(exposure, total_capital)

        return PortfolioRiskReport(
            exposure=exposure,
            overexposure_flags=overexposure_flags,
            duplicated_risk_flags=duplicated_risk_flags,
            high_correlation_pairs=high_correlation_pairs,
            systemic_risk_notes=systemic_risk_notes,
        )
