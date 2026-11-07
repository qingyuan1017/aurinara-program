"""SDTM route composition."""

from fastapi import APIRouter

from app.sdtm.acrf import router as acrf_router
from app.sdtm.authoring import router as authoring_router
from app.sdtm.csdrg import router as csdrg_router
from app.sdtm.define import router as define_router
from app.sdtm.imported_domains import router as imported_domains_router
from app.sdtm.workbench_routes import router as workbench_router

router = APIRouter()
router.include_router(workbench_router)
router.include_router(authoring_router)
router.include_router(imported_domains_router)
router.include_router(acrf_router)
router.include_router(define_router)
router.include_router(csdrg_router)
