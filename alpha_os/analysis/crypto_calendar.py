from datetime import datetime, timedelta

from alpha_os.core.models import HalvingEstimate

HALVING_INTERVAL_BLOCKS = 210_000
AVERAGE_BLOCK_MINUTES = 10.0  # promedio de diseño del protocolo, no medido en vivo


def next_btc_halving_estimate(current_block_height: int) -> HalvingEstimate:
    """Determinístico: el halving ocurre cada 210,000 bloques exactos. La
    fecha es una estimación basada en el tiempo de bloque promedio de
    diseño (10 min) — el hashrate real la adelanta o atrasa."""
    next_halving_block = ((current_block_height // HALVING_INTERVAL_BLOCKS) + 1) * HALVING_INTERVAL_BLOCKS
    blocks_remaining = next_halving_block - current_block_height
    minutes_remaining = blocks_remaining * AVERAGE_BLOCK_MINUTES
    estimated_date = datetime.utcnow() + timedelta(minutes=minutes_remaining)
    return HalvingEstimate(
        current_block_height=current_block_height,
        next_halving_block=next_halving_block,
        blocks_remaining=blocks_remaining,
        estimated_date=estimated_date,
        estimated_days_remaining=round(minutes_remaining / 60 / 24, 1),
    )
