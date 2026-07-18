from fastapi import APIRouter, Depends

from alpha_os.adapters.broker.ibkr_adapter import IBKRAdapter
from alpha_os.api.deps import get_ibkr_adapter, get_position_manager, get_signal_engine
from alpha_os.core.models import DailyTradingRunResult
from alpha_os.engine.signal_engine import SignalEngine
from alpha_os.jobs.daily_trading_job import get_last_run, run_daily_trading_job
from alpha_os.positions.position_manager import PositionManager

router = APIRouter(prefix="/jobs/daily-trading", tags=["jobs"])


@router.post("/run-now", response_model=DailyTradingRunResult)
async def run_now(
    signal_engine: SignalEngine = Depends(get_signal_engine),
    ibkr: IBKRAdapter = Depends(get_ibkr_adapter),
    position_manager: PositionManager = Depends(get_position_manager),
):
    """Dispara el bot de trading diario inmediatamente, sin esperar al
    siguiente ciclo automático de 24h — útil para probarlo ahora mismo."""
    return await run_daily_trading_job(signal_engine, ibkr, position_manager)


@router.get("/last-run", response_model=DailyTradingRunResult | None)
def last_run():
    return get_last_run()
