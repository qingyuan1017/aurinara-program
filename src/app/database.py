"""SQLAlchemy engine, session, and declarative-base factories."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import URL, MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base for application-owned SQLAlchemy models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def build_database_url(settings: Settings) -> str | URL:
    """Resolve either the local URL or production split database settings."""
    if settings.database_url:
        return settings.database_url
    password = settings.database_password
    return URL.create(
        "postgresql+psycopg",
        username=settings.database_user,
        password=password.get_secret_value() if password is not None else None,
        host=settings.database_host,
        port=settings.database_port,
        database=settings.database_name,
        query={"sslmode": settings.database_ssl_mode},
    )


def create_database_engine(settings: Settings) -> Engine:
    """Create an engine without connecting at import time."""

    return create_engine(
        build_database_url(settings),
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_recycle=settings.database_pool_recycle_seconds,
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create the explicit session factory used by application boundaries."""

    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield one session and guarantee close without choosing commit semantics."""

    session = factory()
    try:
        yield session
    finally:
        session.close()
