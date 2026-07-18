import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from alpha_os.api import (
    routes_brief,
    routes_broker,
    routes_calendar,
    routes_defi,
    routes_jobs,
    routes_learning,
    routes_market_context,
    routes_narrative,
    routes_onchain,
    routes_portfolio,
    routes_positions,
    routes_signals,
)
from alpha_os.api.deps import get_ibkr_adapter, get_position_manager, get_signal_engine
from alpha_os.jobs.daily_trading_job import run_daily_trading_job

STATIC_DIR = Path(__file__).parent / "static"
DAILY_JOB_INTERVAL_SECONDS = 24 * 60 * 60

logger = logging.getLogger("alpha_os.daily_job")


async def _daily_trading_loop():
    """Corre el bot de trading diario cada 24h mientras el proceso de
    AlphaOS siga vivo (sin dependencia externa tipo cron/launchd — ver
    README para el trade-off aceptado). Deliberadamente NO corre de
    inmediato al arrancar: reiniciar el servidor durante desarrollo/depuración
    no debe disparar una corrida real de trading — la primera corrida del
    día se dispara a mano vía `POST /jobs/daily-trading/run-now`."""
    while True:
        await asyncio.sleep(DAILY_JOB_INTERVAL_SECONDS)
        try:
            result = await run_daily_trading_job(
                get_signal_engine(), get_ibkr_adapter(), get_position_manager()
            )
            for line in result.actions:
                logger.info(line)
        except Exception:
            logger.exception("Corrida del bot de trading diario falló")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_daily_trading_loop())
    yield
    task.cancel()


app = FastAPI(
    title="AlphaOS",
    description="Motor institucional de inteligencia financiera — arquitectura y esqueleto.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(routes_signals.router)
app.include_router(routes_positions.router)
app.include_router(routes_portfolio.router)
app.include_router(routes_market_context.router)
app.include_router(routes_onchain.router)
app.include_router(routes_narrative.router)
app.include_router(routes_calendar.router)
app.include_router(routes_defi.router)
app.include_router(routes_learning.router)
app.include_router(routes_broker.router)
app.include_router(routes_brief.router)
app.include_router(routes_jobs.router)


@app.get("/health")
def health():
    return {"status": "ok"}


# Alpha Brief (alpha_os/static/index.html) es la pantalla principal — Swagger
# sigue disponible en /docs para depuración, pero no es lo primero que se ve.
@app.get("/")
def alpha_brief_home():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
