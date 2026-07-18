from fastapi import APIRouter, Depends, HTTPException

from alpha_os.api.deps import get_signal_engine
from alpha_os.core.enums import AssetClass
from alpha_os.core.models import Signal
from alpha_os.engine.signal_engine import SignalEngine

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/{ticker}", response_model=Signal | None)
def get_signal(
    ticker: str,
    asset_class: AssetClass = AssetClass.EQUITY,
    engine: SignalEngine = Depends(get_signal_engine),
):
    try:
        return engine.generate_signal(ticker, asset_class)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
