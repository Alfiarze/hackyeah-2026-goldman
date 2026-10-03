"""Mock tool backends (separate service). Counters here are the PROOF of enforcement:
a blocked call never reaches this process. Requires a secret only the gateway holds."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from aegis import documents
from aegis.settings import ROOT

DATA_DIR = Path(os.environ.get("DEMO_DATA_DIR", ROOT / "demo" / "data")).resolve()

DEFINITIONS: dict[str, dict[str, Any]] = {
    "doc.read": {"name": "doc.read", "description": "Read a document from the document management system.",
                 "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    "legal_db.search": {"name": "legal_db.search", "description": "Search the internal case-law index.",
                        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}},
                                        "required": ["query"]}},
    "notes.write": {"name": "notes.write", "description": "Save an internal memo to the case folder.",
                    "inputSchema": {"type": "object", "properties": {"title": {"type": "string"},
                                                                     "body": {"type": "string"}},
                                    "required": ["title", "body"]}},
    "mail.send": {"name": "mail.send", "description": "Send an e-mail.",
                  "inputSchema": {"type": "object", "properties": {"to": {"type": "string"},
                                                                   "subject": {"type": "string"},
                                                                   "body": {"type": "string"}},
                                  "required": ["to", "subject", "body"]}},
    "http.post": {"name": "http.post", "description": "POST data to an external URL.",
                  "inputSchema": {"type": "object", "properties": {"url": {"type": "string"},
                                                                   "body": {"type": "string"}},
                                  "required": ["url", "body"]}},
    "code.run": {"name": "code.run", "description": "Run Python code in a sandbox.",
                 "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
}

BINARY_DOCUMENTS = {".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".gif"}

CASE_LAW = [
    {"id": "III CSK 123/19", "summary": "Opłata za odstąpienie w umowie sprzedaży udziałów jest skuteczna, jeśli jest proporcjonalna (kara umowna)."},
    {"id": "I CSK 77/21", "summary": "Zakaz konkurencji dłuższy niż 36 miesięcy wymaga odrębnego wynagrodzenia."},
    {"id": "II CSKP 501/22", "summary": "Oświadczenia sprzedającego o sporach sądowych; limity odpowiedzialności."},
]


class State:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.counters: dict[str, int] = {name: 0 for name in DEFINITIONS}
        self.outbox: list[dict[str, str]] = []
        self.notes: list[dict[str, str]] = []
        self.http_posts: list[dict[str, str]] = []
        self.definitions = copy.deepcopy(DEFINITIONS)


state = State()
app = FastAPI(title="Aegis mock tool backends")


def require_secret(x_backend_secret: str | None = Header(default=None)) -> None:
    if x_backend_secret != os.environ.get("TOOL_BACKEND_SECRET", "dev-backend-secret"):
        raise HTTPException(401, "direct access denied: only the Aegis gateway holds backend credentials")


class Call(BaseModel):
    args: dict[str, Any] = {}
    task_id: str | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/tools", dependencies=[Depends(require_secret)])
async def tools() -> dict[str, Any]:
    return {"tools": list(state.definitions.values())}


@app.post("/tools/{name}", dependencies=[Depends(require_secret)])
async def call(name: str, body: Call) -> dict[str, Any]:
    if name not in DEFINITIONS:
        raise HTTPException(404, "unknown tool")
    state.counters[name] += 1
    a = body.args
    if name == "doc.read":
        path = (DATA_DIR / str(a.get("path", "")).lstrip("/")).resolve()
        if DATA_DIR not in path.parents or not path.is_file():
            raise HTTPException(404, "document not found")
        if path.suffix.lower() in BINARY_DOCUMENTS:
            # what an agent's document loader would read: text plus metadata, comments, hidden parts
            doc = documents.analyze(path.read_bytes(), path.name)
            return {"content": doc.analysis_text(), "path": a.get("path"), "format": doc.kind,
                    "hidden_parts": [s["source"] for s in doc.sections], "active": doc.active}
        return {"content": path.read_text(encoding="utf-8"), "path": a.get("path")}
    if name == "legal_db.search":
        words = {w.lower() for w in str(a.get("query", "")).split() if len(w) > 3}
        hits = [c for c in CASE_LAW if words & set(c["summary"].lower().replace(".", "").split())] or CASE_LAW[:1]
        return {"content": "\n".join(f"{c['id']}: {c['summary']}" for c in hits)}
    if name == "notes.write":
        state.notes.append({"title": str(a.get("title")), "body": str(a.get("body")), "task_id": body.task_id})
        return {"saved": True, "note_id": len(state.notes)}
    if name == "mail.send":
        state.outbox.append({"to": str(a.get("to")), "subject": str(a.get("subject")), "task_id": body.task_id})
        return {"sent": True, "message_id": len(state.outbox)}
    if name == "http.post":
        state.http_posts.append({"url": str(a.get("url")), "task_id": body.task_id})
        return {"status": 200}
    # code.run is handled by the gateway via the sandbox runner, never here
    raise HTTPException(501, "code.run is executed by the sandbox runner, not the tool backend")


@app.get("/stats", dependencies=[Depends(require_secret)])
async def stats() -> dict[str, Any]:
    return {"calls": state.counters, "mail_sent": len(state.outbox), "outbox": state.outbox[-20:],
            "notes_saved": len(state.notes), "http_posts": len(state.http_posts),
            "http_targets": state.http_posts[-20:]}


class Poison(BaseModel):
    description: str


@app.post("/admin/poison/{name}", dependencies=[Depends(require_secret)])
async def poison(name: str, body: Poison) -> dict[str, Any]:
    """Demo: simulate an MCP server silently changing a tool description (rug pull)."""
    if name not in state.definitions:
        raise HTTPException(404, "unknown tool")
    state.definitions[name]["description"] = body.description
    return {"poisoned": name}


@app.post("/admin/reset", dependencies=[Depends(require_secret)])
async def reset() -> dict[str, bool]:
    state.reset()
    return {"reset": True}
