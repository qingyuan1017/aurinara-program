"""ADaM route composition."""

from fastapi import APIRouter

from app.adam.adrg import router as adrg_router
from app.adam.define import router as define_router
from app.adam.workbench_routes import router as workbench_router

router = APIRouter()
router.include_router(workbench_router)
router.include_router(define_router)
router.include_router(adrg_router)
