"""TLF route composition."""

from fastapi import APIRouter

from app.assistance.routes import proposal_router
from app.tlf.models import TlfWorkbench
from app.tlf.workbench_routes import router as workbench_router

router = APIRouter()
router.include_router(workbench_router)
router.include_router(
    proposal_router(
        module_key="tlf",
        collection="tlf-workbenches",
        aggregate_model=TlfWorkbench,
        not_found_code="tlf_not_found",
        not_found_title="TLF workbench not found",
    )
)
