from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


# Neon URLs use libpq options; SQLAlchemy's asyncpg driver expects ssl.
database_url = make_url(settings.DATABASE_URL)
if database_url.drivername in {"postgres", "postgresql"}:
    database_url = database_url.set(drivername="postgresql+asyncpg")

options = dict(database_url.query)
ssl_mode = options.pop("sslmode", None)
options.pop("channel_binding", None)
if ssl_mode is not None:
    options.setdefault("ssl", ssl_mode)
database_url = database_url.set(query=options)

# Bound connection waits and disable asyncpg's statement cache for pooling.
connect_args = (
    {"timeout": 20, "statement_cache_size": 0}
    if database_url.drivername == "postgresql+asyncpg"
    else {}
)

# Manage connections to the database configured in .env.
engine = create_async_engine(
    database_url,
    pool_pre_ping=True,
    connect_args=connect_args,
)

# Create database sessions for requests and background jobs.
AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


# Our database models will inherit from this class.
class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
