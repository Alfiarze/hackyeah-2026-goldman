"""Budget escrow: atomic reserve-before-execute across all scopes in ONE Postgres transaction."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import asyncpg

from mandate.policy import Limit


@dataclass
class Scope:
    scope_id: str
    limit: Limit | None = None  # None = row must already exist (e.g. task scope created with the task)


class BudgetExceeded(Exception):
    def __init__(self, scope_id: str, dimension: str, detail: dict):
        super().__init__(f"{scope_id}: {dimension}")
        self.scope_id = scope_id
        self.dimension = dimension
        self.detail = detail


class Escrow:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def ensure(self, conn: asyncpg.Connection, scope: Scope) -> None:
        if scope.limit is None:
            return
        await conn.execute(
            """INSERT INTO budgets (scope_id, token_limit, calls_limit, concurrency_limit)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (scope_id) DO UPDATE SET token_limit = EXCLUDED.token_limit,
                   calls_limit = EXCLUDED.calls_limit, concurrency_limit = EXCLUDED.concurrency_limit""",
            scope.scope_id, scope.limit.tokens, scope.limit.calls, scope.limit.concurrency,
        )

    async def reserve(self, task_id: str | None, scopes: list[Scope], tokens: int, calls: int = 1) -> str:
        """All-or-nothing: either every scope accepts the reservation or none is touched."""
        ordered = sorted({s.scope_id: s for s in scopes}.values(), key=lambda s: s.scope_id)  # no deadlocks
        async with self.pool.acquire() as conn, conn.transaction():
            for scope in ordered:
                await self.ensure(conn, scope)
                ok = await conn.fetchval(
                    """UPDATE budgets SET reserved = reserved + $2, calls_used = calls_used + $3,
                              active_calls = active_calls + 1
                       WHERE scope_id = $1
                         AND spent + reserved + $2 <= token_limit
                         AND calls_used + $3 <= calls_limit
                         AND active_calls < concurrency_limit
                       RETURNING scope_id""",
                    scope.scope_id, tokens, calls,
                )
                if ok is None:
                    row = await conn.fetchrow("SELECT * FROM budgets WHERE scope_id=$1", scope.scope_id)
                    raise BudgetExceeded(scope.scope_id, _dimension(row, tokens, calls),
                                         dict(row) if row else {"missing": True} | {"requested": tokens})
            res_id = uuid.uuid4().hex
            await conn.execute(
                "INSERT INTO reservations (id, task_id, scope_ids, amount) VALUES ($1, $2, $3, $4)",
                res_id, task_id, [s.scope_id for s in ordered], tokens,
            )
        return res_id

    async def settle(self, res_id: str, actual_tokens: int) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            res = await conn.fetchrow(
                "UPDATE reservations SET status='settled', actual=$2, settled_at=now() "
                "WHERE id=$1 AND status='active' RETURNING scope_ids, amount", res_id, actual_tokens,
            )
            if res is None:
                return
            # actual usage is charged even if it exceeds the estimate (bounded by max_tokens)
            await conn.execute(
                """UPDATE budgets SET reserved = reserved - $2, spent = spent + $3,
                          active_calls = active_calls - 1
                   WHERE scope_id = ANY($1)""",
                res["scope_ids"], res["amount"], actual_tokens,
            )

    async def mark_uncertain(self, res_id: str) -> None:
        """Provider outcome unknown (timeout): keep the tokens reserved until reconciled, free the slot."""
        async with self.pool.acquire() as conn, conn.transaction():
            res = await conn.fetchrow(
                "UPDATE reservations SET status='uncertain' WHERE id=$1 AND status='active' RETURNING scope_ids",
                res_id,
            )
            if res:
                await conn.execute(
                    "UPDATE budgets SET active_calls = active_calls - 1 WHERE scope_id = ANY($1)", res["scope_ids"]
                )

    async def reconcile(self, res_id: str, actual_tokens: int) -> bool:
        """Manual settle of an 'uncertain' reservation (admin)."""
        async with self.pool.acquire() as conn, conn.transaction():
            res = await conn.fetchrow(
                "UPDATE reservations SET status='settled', actual=$2, settled_at=now() "
                "WHERE id=$1 AND status='uncertain' RETURNING scope_ids, amount", res_id, actual_tokens,
            )
            if res is None:
                return False
            await conn.execute(
                "UPDATE budgets SET reserved = reserved - $2, spent = spent + $3 WHERE scope_id = ANY($1)",
                res["scope_ids"], res["amount"], actual_tokens,
            )
            return True


def _dimension(row, tokens: int, calls: int) -> str:
    if row is None:
        return "missing_scope"
    if row["spent"] + row["reserved"] + tokens > row["token_limit"]:
        return "tokens"
    if row["calls_used"] + calls > row["calls_limit"]:
        return "calls"
    return "concurrency"
