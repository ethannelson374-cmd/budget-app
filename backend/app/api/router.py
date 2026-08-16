from fastapi import APIRouter

from app.api import advisor, auth, budget, finance, insights, notifications, operations, plaid, planning, privacy, reports, security, setup

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(setup.router)
api_router.include_router(auth.router)
api_router.include_router(security.router)
api_router.include_router(operations.router)
api_router.include_router(notifications.router)
api_router.include_router(finance.router)
api_router.include_router(budget.router)
api_router.include_router(planning.router)
api_router.include_router(insights.router)
api_router.include_router(advisor.router)
api_router.include_router(reports.router)
api_router.include_router(privacy.router)
api_router.include_router(plaid.router)
