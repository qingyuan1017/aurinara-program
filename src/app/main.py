"""FastAPI application composition."""

from typing import cast

from fastapi import APIRouter, FastAPI
from sqlalchemy.orm import Session, sessionmaker

from app import __version__
from app.api.auth import JwksTokenVerifier, TokenVerifier
from app.api.catalogs import router as catalogs_router
from app.api.health import router as health_router
from app.api.middleware import RequestContextMiddleware
from app.api.modules import router as modules_router
from app.api.traceability import router as traceability_router
from app.artifacts.builds import router as artifact_builds_router
from app.artifacts.routes import router as artifacts_router
from app.artifacts.storage import ObjectStorage, S3ObjectStorage
from app.common.logging import configure_logging
from app.common.problems import install_exception_handlers
from app.composition import build_module_registry
from app.config import Settings, get_settings
from app.database import create_database_engine, create_session_factory
from app.execution.routes import router as execution_router
from app.integration.routes import router as integration_router
from app.kernel.registry import ModuleRegistry
from app.reconciliation.routes import router as reconciliation_router
from app.reference.routes import router as reference_router
from app.review.routes import router as review_router
from app.studies.routes import router as studies_router
from app.terminology.routes import router as terminology_router
from app.validation.routes import router as validation_router


def create_app(
    settings: Settings | None = None,
    module_registry: ModuleRegistry | None = None,
    session_factory: sessionmaker[Session] | None = None,
    object_storage: ObjectStorage | None = None,
    token_verifier: TokenVerifier | None = None,
) -> FastAPI:
    """Create a fully composed API without external I/O at import time."""

    resolved_settings = settings or get_settings()
    registry = module_registry or build_module_registry()
    resolved_session_factory = session_factory or create_session_factory(
        create_database_engine(resolved_settings)
    )
    configure_logging(resolved_settings.app_log_level)

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version or __version__,
        docs_url="/docs",
        redoc_url=None,
        openapi_url=f"{resolved_settings.app_api_prefix}/openapi.json",
    )
    application.state.settings = resolved_settings
    application.state.module_registry = registry
    application.state.session_factory = resolved_session_factory
    application.state.object_storage = object_storage or S3ObjectStorage(resolved_settings)
    application.state.token_verifier = token_verifier or JwksTokenVerifier(resolved_settings)
    application.state.infrastructure_readiness_enabled = resolved_settings.app_env != "test"
    application.add_middleware(RequestContextMiddleware)
    install_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(modules_router, prefix=resolved_settings.app_api_prefix)
    application.include_router(studies_router, prefix=resolved_settings.app_api_prefix)
    application.include_router(artifacts_router, prefix=resolved_settings.app_api_prefix)
    application.include_router(artifact_builds_router, prefix=resolved_settings.app_api_prefix)
    application.include_router(execution_router, prefix=resolved_settings.app_api_prefix)
    for module_router in registry.routers():
        application.include_router(
            cast(APIRouter, module_router), prefix=resolved_settings.app_api_prefix
        )
    application.include_router(catalogs_router, prefix=resolved_settings.app_api_prefix)
    application.include_router(terminology_router, prefix=resolved_settings.app_api_prefix)
    application.include_router(reference_router, prefix=resolved_settings.app_api_prefix)
    application.include_router(review_router, prefix=resolved_settings.app_api_prefix)
    application.include_router(reconciliation_router, prefix=resolved_settings.app_api_prefix)
    application.include_router(traceability_router, prefix=resolved_settings.app_api_prefix)
    application.include_router(integration_router, prefix=resolved_settings.app_api_prefix)
    application.include_router(validation_router, prefix=resolved_settings.app_api_prefix)
    return application


app = create_app()
