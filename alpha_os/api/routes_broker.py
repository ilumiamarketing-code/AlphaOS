from fastapi import APIRouter, Depends

from alpha_os.adapters.broker.ibkr_adapter import IBKRAdapter
from alpha_os.api.deps import get_ibkr_adapter
from alpha_os.core.models import BrokerAccountSummary, BrokerPosition, PaperOrderRequest, PaperOrderResult

router = APIRouter(prefix="/broker", tags=["broker"])


@router.get("/account-summary", response_model=BrokerAccountSummary)
async def get_account_summary(adapter: IBKRAdapter = Depends(get_ibkr_adapter)):
    """Requiere TWS o IB Gateway corriendo localmente con la API habilitada
    (Configure > API > Settings > Enable ActiveX and Socket Clients).
    `is_paper_account` viene directo del prefijo de cuenta que asigna IBKR
    ('DU' = práctica), nunca se asume."""
    return await adapter.get_account_summary()


@router.get("/positions", response_model=list[BrokerPosition])
async def get_positions(adapter: IBKRAdapter = Depends(get_ibkr_adapter)):
    return await adapter.get_positions()


@router.post("/test-order", response_model=PaperOrderResult)
async def place_test_order(request: PaperOrderRequest, adapter: IBKRAdapter = Depends(get_ibkr_adapter)):
    """Envía una orden real a IBKR — pero **solo si la cuenta conectada es
    de práctica** (prefijo 'DU'). Si TWS/Gateway está logueado en una
    cuenta real, esta orden se rechaza en vez de ejecutarse; este sistema
    nunca coloca órdenes en dinero real."""
    return await adapter.place_test_order(request)
