"""Documents route composition."""

from fastapi import APIRouter

from app.documents.document_routes import router as document_router

router = APIRouter()
router.include_router(document_router)
