import json
from pathlib import Path

import asyncpg


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def create_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=1, max_size=20, init=_init_conn)


async def migrate(pool: asyncpg.Pool, sql_dir: Path) -> None:
    """Apply db/init/*.sql at startup. Every file is idempotent, so this is safe on each boot and
    removes the need for docker-entrypoint-initdb.d bind mounts (Coolify, Kubernetes)."""
    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock(4201)")
        try:
            for f in sorted(sql_dir.glob("*.sql")):
                await conn.execute(f.read_text())
        finally:
            await conn.execute("SELECT pg_advisory_unlock(4201)")
