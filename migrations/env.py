"""Alembic environment using application settings without import-time connections."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import model_registry  # noqa: F401
from app.config import get_settings
from app.database import Base, build_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = build_database_url(get_settings())
rendered_database_url = (
    database_url.render_as_string(hide_password=False)
    if hasattr(database_url, "render_as_string")
    else database_url
)
config.set_main_option("sqlalchemy.url", rendered_database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations by emitting SQL without opening a connection."""

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the configured database."""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
