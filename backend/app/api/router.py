from fastapi import APIRouter

from app.api import auth, finance, setup

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(setup.router)
api_router.include_router(auth.router)
api_router.include_router(finance.router)
