"""Idempotent ownership migration for the existing single-instance database."""
from sqlalchemy import inspect, text
from app.db import Base
from app import models  # Register all tables before create_all.


async def initialize_schema(connection):
    await connection.run_sync(Base.metadata.create_all)
    columns = await connection.run_sync(
        lambda conn: {column["name"] for column in inspect(conn).get_columns("uploads")}
    )
    if "user_id" not in columns:
        await connection.execute(text("ALTER TABLE uploads ADD COLUMN user_id VARCHAR REFERENCES users(id)"))
        await connection.execute(text("CREATE INDEX ix_uploads_user_id ON uploads (user_id)"))
    # Old public demo rows remain unowned and inaccessible; never assign them
    # to the first person who signs in.
