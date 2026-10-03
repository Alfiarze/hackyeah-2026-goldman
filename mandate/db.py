import os

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://goldman:goldman@localhost:5432/goldman"
)

engine: AsyncEngine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
