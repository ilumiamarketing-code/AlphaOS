from fastapi import APIRouter, Depends, HTTPException

from alpha_os.api.deps import get_journal_manager, get_position_manager
from alpha_os.core.models import OperationEntry, Position, PostMortem, RiskParameters
from alpha_os.positions.journal import JournalManager
from alpha_os.positions.position_manager import PositionManager, PositionNotFoundError

router = APIRouter(prefix="/positions", tags=["positions"])


@router.post("", response_model=Position)
def register_operation(
    entry: OperationEntry,
    risk_parameters: RiskParameters,
    position_manager: PositionManager = Depends(get_position_manager),
    journal_manager: JournalManager = Depends(get_journal_manager),
):
    position = position_manager.register_operation(entry, risk_parameters)
    journal_manager.open_entry(position.id)
    return position


@router.get("", response_model=list[Position])
def list_positions(
    active_only: bool = True,
    position_manager: PositionManager = Depends(get_position_manager),
):
    return position_manager.list_active() if active_only else position_manager.list_all()


@router.get("/{position_id}", response_model=Position)
def get_position(
    position_id: str, position_manager: PositionManager = Depends(get_position_manager)
):
    try:
        return position_manager.get(position_id)
    except PositionNotFoundError:
        raise HTTPException(status_code=404, detail="Posición no encontrada") from None


@router.post("/{position_id}/mark-price", response_model=Position)
def mark_price(
    position_id: str,
    price: float,
    position_manager: PositionManager = Depends(get_position_manager),
):
    try:
        return position_manager.update_mark_price(position_id, price)
    except PositionNotFoundError:
        raise HTTPException(status_code=404, detail="Posición no encontrada") from None


@router.post("/{position_id}/close", response_model=Position)
def close_position(
    position_id: str,
    exit_price: float,
    position_manager: PositionManager = Depends(get_position_manager),
    journal_manager: JournalManager = Depends(get_journal_manager),
):
    try:
        position = position_manager.close(position_id, exit_price)
    except PositionNotFoundError:
        raise HTTPException(status_code=404, detail="Posición no encontrada") from None
    journal_manager.close_out(position_id)
    return position


@router.get("/{position_id}/post-mortem", response_model=PostMortem)
def get_post_mortem(
    position_id: str,
    position_manager: PositionManager = Depends(get_position_manager),
    journal_manager: JournalManager = Depends(get_journal_manager),
):
    """Requiere que la posición esté cerrada y se haya abierto a partir de
    una Signal del motor (`original_signal`) — si no, se levanta un error
    explícito en vez de fabricar un post-mortem sin evidencia real."""
    try:
        position_manager.get(position_id)
    except PositionNotFoundError:
        raise HTTPException(status_code=404, detail="Posición no encontrada") from None
    try:
        return journal_manager.generate_post_mortem(position_id)
    except (ValueError, NotImplementedError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
