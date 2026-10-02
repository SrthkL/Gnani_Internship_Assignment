import asyncio

from app.db import Base, engine
from app import models  # Register the Upload table with Base.metadata.


async def init_db():
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        print("Database tables created.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(init_db())