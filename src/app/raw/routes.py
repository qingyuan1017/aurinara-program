"""Raw route composition."""

from fastapi import APIRouter

from app.raw.workbench_routes import router as workbench_router

router = APIRouter()
router.include_router(workbench_router)
