"""ADaM route composition."""

from fastapi import APIRouter

from app.adam.adrg import router as adrg_router
from app.adam.define import router as define_router
from app.adam.models import AdamWorkbench
from app.adam.workbench_routes import router as workbench_router
from app.assistance.routes import proposal_router

router = APIRouter()
router.include_router(workbench_router)
router.include_router(define_router)
router.include_router(adrg_router)
router.include_router(
    proposal_router(
        module_key="adam",
        collection="adam-workbenches",
        aggregate_model=AdamWorkbench,
        not_found_code="adam_not_found",
        not_found_title="ADaM workbench not found",
    )
)
