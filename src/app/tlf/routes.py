"""TLF route composition."""

from fastapi import APIRouter

from app.tlf.workbench_routes import router as workbench_router

router = APIRouter()
router.include_router(workbench_router)
