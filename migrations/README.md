# Database migrations

All persistent schema changes use the single ordered Alembic history in this directory.
Module-owned tables remain identifiable by their module prefix, but modules do not create
tables dynamically at application startup.
