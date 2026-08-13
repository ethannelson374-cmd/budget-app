from fastapi import APIRouter

from app.api import auth, budget, finance, insights, plaid, planning, setup

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(setup.router)
api_router.include_router(auth.router)
api_router.include_router(finance.router)
api_router.include_router(budget.router)
api_router.include_router(planning.router)
api_router.include_router(insights.router)
api_router.include_router(plaid.router)
