"""Test harness: real Postgres (database `goldman_test`), real gateway app, real backend app (ASGI),
semantic guard on the local heuristic backend (no model server needed). Mark live-model tests with `-m live`."""

import asyncio
import sys
import os
import shutil
from pathlib import Path

import asyncpg
import httpx
import pytest
from asgi_lifespan import LifespanManager

from fastapi import FastAPI

from aegis.settings import ROOT as _ROOT

sys.path.insert(0, str(_ROOT / "sdk"))  # the SDK ships as its own package in sdk/

from aegis import backends
from aegis.app import create_app
from aegis.settings import ROOT, Settings

# A fake sandbox runner: no Docker. Canned results keyed by a marker in the code, so engine wiring is
# tested deterministically in CI. The real isolation is exercised live via aegis/sandbox.py.
sandbox_app = FastAPI()


@sandbox_app.post("/run")
async def _fake_run(body: dict):
    code = body.get("code", "")
    if "NETWORK" in code:
        return {"status": "nonzero_exit", "exit_code": 1, "stdout": "", "stderr": "Network is unreachable",
                "duration_ms": 5.0, "network_attempted": True, "notes": ["code tried to use the network"]}
    if "LOOP" in code:
        return {"status": "timeout", "exit_code": None, "stdout": "", "stderr": "", "duration_ms": 10.0,
                "network_attempted": False, "notes": ["killed after the limit"]}
    return {"status": "ok", "exit_code": 0, "stdout": "hello from the sandbox", "stderr": "",
            "duration_ms": 5.0, "network_attempted": False, "notes": []}


ADMIN = {"X-Admin-Key": "test-admin"}
APP = {"X-App-Key": "test-app"}
BASE_DSN = os.environ.get("TEST_DATABASE_URL_BASE", "postgresql://goldman:goldman@localhost:5432")
TEST_DSN = f"{BASE_DSN}/goldman_test"
TABLES = "approvals, tasks, budgets, reservations, audit_events, policy_versions, tool_registry, memory_entries"


def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires the main model server (LLM_BASE_URL)")


@pytest.fixture(scope="session", autouse=True)
def database():
    async def setup():
        admin = await asyncpg.connect(f"{BASE_DSN}/goldman")
        await admin.execute("DROP DATABASE IF EXISTS goldman_test WITH (FORCE)")
        await admin.execute("CREATE DATABASE goldman_test")
        await admin.close()
        conn = await asyncpg.connect(TEST_DSN)
        for f in sorted((ROOT / "db" / "init").glob("*.sql")):
            await conn.execute(f.read_text())
        await conn.close()
    asyncio.run(setup())


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    (tmp_path / "policy").mkdir()
    (tmp_path / "feeds").mkdir()
    shutil.copy(ROOT / "policy" / "policy.yaml", tmp_path / "policy" / "policy.yaml")
    shutil.copy(ROOT / "feeds" / "attacks.yaml", tmp_path / "feeds" / "attacks.yaml")
    return Settings(
        database_url=TEST_DSN,
        policy_path=tmp_path / "policy" / "policy.yaml",
        feed_path=tmp_path / "feeds" / "attacks.yaml",
        llm_base_url="",  # no model server in CI: AI review runs on the local scorer
        llm_api_key="",
        admin_api_key="test-admin",
        app_api_key="test-app",
        lease_secret="test-lease-secret",
        tool_backend_secret="dev-backend-secret",
        agent_keys={"agent-a": "demo-agent", "agent-b": "other-agent"},
        background_tasks=False,
    )


@pytest.fixture
async def app(settings):
    conn = await asyncpg.connect(TEST_DSN)
    await conn.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
    await conn.close()
    backends.state.reset()
    application = create_app(settings, tool_client_factory=lambda: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=backends.app), base_url="http://tools"),
        sandbox_client_factory=lambda: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=sandbox_app), base_url="http://sandbox"))
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw") as c:
        yield c


@pytest.fixture
def gw(app):
    return app.state.gw


@pytest.fixture
def backend():
    return backends.state


@pytest.fixture
def new_task(client):
    async def make(profile="contract_review", client_id="A", agent_key="agent-a", agent_id="demo-agent"):
        resp = await client.post("/v1/tasks", headers=APP, json={
            "principal": "lawyer_anna", "agent_id": agent_id, "profile": profile, "params": {"client": client_id}})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        return body | {"headers": {"Authorization": f"Bearer {agent_key}", "X-Mandate-Lease": body["lease"]}}
    return make


@pytest.fixture
def call(client):
    async def do(task, tool, **args):
        return await client.post(f"/v1/tools/{tool}/call", headers=task["headers"], json={"args": args})
    return do
