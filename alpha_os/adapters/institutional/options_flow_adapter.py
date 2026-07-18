from datetime import date

import yfinance as yf

from alpha_os.core.models import OptionsFlowObservation

# Heurística de un solo corte (sin baseline histórico propio): volumen del
# día superando la mitad del open interest sugiere posicionamiento nuevo
# más que cierre de posiciones existentes. Es un proxy, no confirmación.
UNUSUAL_VOLUME_TO_OI_RATIO = 0.5


class OptionsFlowAdapter:
    """Fuente gratuita (yfinance option_chain, sin API key). Solo el
    vencimiento más próximo — no agrega across strikes/vencimientos."""

    def get_observation(self, ticker: str) -> OptionsFlowObservation | None:
        try:
            tk = yf.Ticker(ticker)
            expirations = tk.options
            if not expirations:
                return None
            # Vencimientos 0DTE (hoy) tienen volumen > OI casi por diseño
            # (contratos que abren y cierran el mismo día) — no es actividad
            # "inusual", es ruido normal. Se prefiere el siguiente vencimiento.
            today = date.today().isoformat()
            target_expiration = next((e for e in expirations if e != today), expirations[0])
            chain = tk.option_chain(target_expiration)
        except Exception:
            return None

        calls, puts = chain.calls, chain.puts
        call_volume = int(calls["volume"].fillna(0).sum())
        put_volume = int(puts["volume"].fillna(0).sum())
        call_oi = int(calls["openInterest"].fillna(0).sum())
        put_oi = int(puts["openInterest"].fillna(0).sum())
        ratio = put_volume / call_volume if call_volume > 0 else None

        return OptionsFlowObservation(
            ticker=ticker,
            expiration=date.fromisoformat(expirations[0]),
            call_volume=call_volume,
            put_volume=put_volume,
            call_open_interest=call_oi,
            put_open_interest=put_oi,
            put_call_volume_ratio=ratio,
            unusual_call_activity=call_oi > 0 and call_volume > call_oi * UNUSUAL_VOLUME_TO_OI_RATIO,
            unusual_put_activity=put_oi > 0 and put_volume > put_oi * UNUSUAL_VOLUME_TO_OI_RATIO,
        )
