"""Alembic environment. Migrations are hand-written (001 core business, 002 negotiation/simulation/audit).

The URL is `config.attributes["url"]` or `-x url=...` if given, else DATABASE_URL from the environment / repository-root `.env`.
`target_metadata` is only used by `alembic check`-style comparisons; the migrations do not depend on the ORM.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = (
    config.attributes.get("url")  # set by tests that migrate TEST_DATABASE_URL programmatically
    or context.get_x_argument(as_dictionary=True).get("url")
    or get_settings().database_url
)
if not url:
    raise RuntimeError("DATABASE_URL is not set (see .env.example) and no -x url=... was given")
config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, include_schemas=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_schemas=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
