from fastapi import APIRouter, Depends

from alpha_os.api.deps import get_portfolio_manager
from alpha_os.core.models import ExposureBreakdown, PortfolioRiskReport
from alpha_os.positions.portfolio_manager import PortfolioManager

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/exposure", response_model=ExposureBreakdown)
def get_exposure(portfolio_manager: PortfolioManager = Depends(get_portfolio_manager)):
    return portfolio_manager.compute_exposure()


@router.get("/risk-report", response_model=PortfolioRiskReport)
def get_risk_report(portfolio_manager: PortfolioManager = Depends(get_portfolio_manager)):
    return portfolio_manager.generate_risk_report()
