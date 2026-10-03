"""Public gateway API: app<->agent (tasks), agent<->model, agent<->tool, agent<->MCP, agent<->agent."""

from __future__ import annotations

import asyncio
import os
import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mandate.attacks import FeedStore
from mandate.audit import Audit
from mandate.db import create_pool, migrate
from mandate.engine import Gateway
from mandate.models import GatewayError
from mandate.policy import PolicyStore
from mandate.semantic import SemanticGuard
from mandate.settings import ROOT, Settings


class TaskCreate(BaseModel):
    principal: str
    agent_id: str
    profile: str
    params: dict[str, str] = {}
    purpose: str = ""

class Delegate(BaseModel):
    agent_id: str
    tools: list[str] | None = None
    resources: list[str] | None = None
    budget_tokens: int | None = None
    purpose: str = ""

class ToolCall(BaseModel):
    args: dict[str, Any] = {}


def create_app(settings: Settings | None = None,
               tool_client_factory: Callable[[], httpx.AsyncClient] | None = None,
               sandbox_client_factory: Callable[[], httpx.AsyncClient] | None = None) -> FastAPI:
    settings = settings or Settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        pool = await create_pool(settings.dsn)
        await migrate(pool, ROOT / "db" / "init")
        audit = Audit(pool)
        policy = PolicyStore(settings.policy_path, pool, audit)
        await policy.load_initial()
        feed = FeedStore(settings.feed_path, audit, settings.feed_url)
        await feed.load_initial()
        semantic = SemanticGuard((settings.llm_base_url, settings.llm_api_key, settings.llm_model)
                                 if settings.main_configured else None, settings.llm_extra_body)
        await semantic.probe()
        tool_client = (tool_client_factory() if tool_client_factory
                       else httpx.AsyncClient(base_url=settings.tools_base_url, timeout=10))
        sandbox_client = (sandbox_client_factory() if sandbox_client_factory
                          else httpx.AsyncClient(base_url=settings.sandbox_base_url, timeout=70)
                          if settings.sandbox_base_url else None)
        app.state.gw = Gateway(settings, pool, policy, feed, audit, semantic, tool_client, sandbox_client)
        background = []
        if settings.background_tasks:
            async def probe_loop():
                while True:
                    await asyncio.sleep(30)
                    await semantic.probe()
            background = [asyncio.create_task(c) for c in
                          (policy.watch(settings.poll_interval), feed.watch(settings.poll_interval), probe_loop())]
        try:
            yield
        finally:
            for t in background:
                t.cancel()
            await tool_client.aclose()
            if sandbox_client:
                await sandbox_client.aclose()
            await pool.close()

    app = FastAPI(title="MANDATE - AI Control Layer", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(GatewayError)
    async def _gateway_error(_req: Request, exc: GatewayError):
        return JSONResponse({"error": {"type": "mandate_rejected", "reason_code": exc.reason_code,
                                       "message": exc.message}}, status_code=exc.status)

    def gw(request: Request) -> Gateway:
        return request.app.state.gw

    def require_app(key: str | None) -> None:
        if key != settings.app_api_key:
            raise GatewayError(401, "APP_UNAUTHENTICATED", "invalid X-App-Key")

    @app.get("/health")
    async def health(request: Request):
        g = gw(request)
        try:
            await g.pool.fetchval("SELECT 1")
            db = "ok"
        except Exception as exc:  # noqa: BLE001
            db = f"error: {type(exc).__name__}"
        status = 200 if db == "ok" else 503
        return JSONResponse({"status": "ok" if status == 200 else "degraded", "db": db,
                             "policy_version": g.policy.version, "feed_version": g.feed.version,
                             "semantic_backend": g.semantic.backend_for(g.policy.active.controls.semantic),
                             "model": g.default_model(g.policy.active)}, status)

    # ------------------------------------------------------------ app <-> agent


    @app.post("/v1/tasks", status_code=201)
    async def create_task(request: Request, body: TaskCreate, x_app_key: str | None = Header(default=None)):
        require_app(x_app_key)
        g = gw(request)
        task = await g.tasks.create(g.policy.active, principal=body.principal, agent_id=body.agent_id,
                                    profile=body.profile, params=body.params, purpose=body.purpose)
        await g.audit.system("TASK_CREATED", actor=body.principal, task_id=task.id,
                             evidence={"profile": body.profile, "agent_id": body.agent_id, "mandate": task.mandate})
        return task.view() | {"lease": g.tasks.lease_for(task)}

    @app.get("/v1/tasks/{task_id}")
    async def get_task(request: Request, task_id: str, authorization: str | None = Header(default=None),
                       x_mandate_lease: str | None = Header(default=None)):
        g = gw(request)
        task = await g.tasks.verify(x_mandate_lease, g.agent_id(authorization))
        if task.id != task_id:
            raise GatewayError(403, "LEASE_TASK_MISMATCH")
        return task.view()

    @app.post("/v1/tasks/{task_id}/complete")
    async def complete_task(request: Request, task_id: str, authorization: str | None = Header(default=None),
                            x_mandate_lease: str | None = Header(default=None)):
        g = gw(request)
        task = await g.tasks.verify(x_mandate_lease, g.agent_id(authorization))
        if task.id != task_id:
            raise GatewayError(403, "LEASE_TASK_MISMATCH")
        await g.tasks.set_status(task_id, "completed")
        await g.audit.system("TASK_COMPLETED", actor=task.principal, task_id=task_id, evidence={})
        return {"task_id": task_id, "status": "completed"}

    # ------------------------------------------------------------ agent <-> agent


    @app.post("/v1/tasks/{task_id}/delegate", status_code=201)
    async def delegate(request: Request, task_id: str, body: Delegate,
                       authorization: str | None = Header(default=None),
                       x_mandate_lease: str | None = Header(default=None)):
        g = gw(request)
        parent = await g.tasks.verify(x_mandate_lease, g.agent_id(authorization))
        if parent.id != task_id:
            raise GatewayError(403, "LEASE_TASK_MISMATCH")
        try:
            child = await g.tasks.delegate(parent, agent_id=body.agent_id, tools=body.tools,
                                           resources=body.resources, budget_tokens=body.budget_tokens,
                                           purpose=body.purpose)
        except GatewayError as exc:
            await g.audit.system("DELEGATION_DENIED", actor=parent.principal, task_id=parent.id,
                                 evidence={"reason_code": exc.reason_code, "message": exc.message,
                                           "requested": body.model_dump()})
            raise
        await g.audit.system("TASK_DELEGATED", actor=parent.principal, task_id=child.id,
                             evidence={"parent": parent.id, "agent_id": body.agent_id, "mandate": child.mandate,
                                       "inherited_classification": child.classification.name})
        return child.view() | {"lease": g.tasks.lease_for(child)}

    # ------------------------------------------------------------ agent <-> model

    @app.post("/v1/chat/completions")
    async def chat(request: Request, body: dict[str, Any] = Body(...),
                   authorization: str | None = Header(default=None),
                   x_mandate_lease: str | None = Header(default=None)):
        g = gw(request)
        status, payload = await g.chat(g.agent_id(authorization), x_mandate_lease, body)
        return JSONResponse(payload, status_code=status)

    # ------------------------------------------------------------ agent <-> tool / MCP


    @app.post("/v1/tools/{tool}/call")
    async def tool_call(request: Request, tool: str, body: ToolCall,
                        authorization: str | None = Header(default=None),
                        x_mandate_lease: str | None = Header(default=None)):
        g = gw(request)
        status, payload = await g.tool_call(g.agent_id(authorization), x_mandate_lease, tool, body.args)
        return JSONResponse(payload, status_code=status)

    @app.post("/mcp")
    async def mcp(request: Request, message: dict[str, Any] = Body(...),
                  authorization: str | None = Header(default=None),
                  x_mandate_lease: str | None = Header(default=None)):
        g = gw(request)
        return await g.mcp(g.agent_id(authorization), x_mandate_lease, message)

    # ------------------------------------------------------------ supply chain

    @app.post("/v1/models/register")
    async def register_model(request: Request, payload: dict[str, Any] = Body(...),
                             x_app_key: str | None = Header(default=None)):
        require_app(x_app_key)
        status, body = await gw(request).register_model(payload)
        return JSONResponse(body, status_code=status)

    # ------------------------------------------------------------ admin + dashboard

    from mandate.admin import router as admin_router

    app.include_router(admin_router)

    dashboard_dir = Path(os.environ.get("DASHBOARD_DIR", ROOT / "dashboard" / "dist"))
    if dashboard_dir.is_dir():
        app.mount("/dashboard", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/dashboard/")

    return app


app = create_app()
