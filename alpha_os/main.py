from fastapi import FastAPI

from alpha_os.api import (
    routes_broker,
    routes_calendar,
    routes_defi,
    routes_learning,
    routes_market_context,
    routes_narrative,
    routes_onchain,
    routes_portfolio,
    routes_positions,
    routes_signals,
)

app = FastAPI(
    title="AlphaOS",
    description="Motor institucional de inteligencia financiera — arquitectura y esqueleto.",
    version="0.1.0",
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


@app.get("/health")
def health():
    return {"status": "ok"}
