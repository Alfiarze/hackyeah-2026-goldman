"""Sandbox runner: executes untrusted code in a throw-away, locked-down Docker container.

Only THIS service talks to the Docker daemon (never the gateway). Each run gets a fresh container with
no network, a read-only root filesystem, a memory and CPU cap, a process limit, dropped capabilities and
a hard timeout, then the container is removed. If the code misbehaves it dies inside the container and the
host is untouched. The result is evidence (output, exit code, whether it timed out / ran out of memory /
tried to reach the network), fed back into the audit trail.

This contains the blast radius of code the gateway chose to run; it does not replace the policy rules that
decide whether running it is allowed at all.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "python:3.12-slim")
SANDBOX_SECRET = os.environ.get("SANDBOX_SECRET", "dev-sandbox-secret")
MAX_WALL_SECONDS = int(os.environ.get("SANDBOX_MAX_WALL_SECONDS", "10"))
MEM_LIMIT = os.environ.get("SANDBOX_MEM_LIMIT", "256m")
CPU_LIMIT = os.environ.get("SANDBOX_CPU_LIMIT", "0.5")
PIDS_LIMIT = os.environ.get("SANDBOX_PIDS_LIMIT", "64")


@dataclass
class RunResult:
    status: str                       # ok | nonzero_exit | timeout | oom | denied | runner_error
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    network_attempted: bool = False
    notes: list[str] = field(default_factory=list)

    def public(self) -> dict:
        clip = lambda s: s if len(s) <= 4000 else s[:4000] + "\n…[truncated]"  # noqa: E731
        return {"status": self.status, "exit_code": self.exit_code, "stdout": clip(self.stdout),
                "stderr": clip(self.stderr), "duration_ms": round(self.duration_ms, 1),
                "network_attempted": self.network_attempted, "notes": self.notes}


def _docker_args() -> list[str]:
    """Run flags that box the container in. --network none is the key control for exfiltration via code."""
    return [
        "docker", "run", "--rm", "-i", "--name", f"mandate-sbx-{uuid.uuid4().hex[:10]}",
        "--network", "none",                 # no outbound connections at all
        "--read-only",                       # root filesystem is immutable
        "--tmpfs", "/tmp:rw,size=16m,noexec", # a small scratch area, no executables
        "--memory", MEM_LIMIT, "--memory-swap", MEM_LIMIT,
        "--cpus", CPU_LIMIT, "--pids-limit", PIDS_LIMIT,
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "65534:65534",             # nobody
        "-w", "/tmp",
        SANDBOX_IMAGE,
        # code is piped in on stdin, so there is no bind mount (a mount path would resolve on the host,
        # not inside this runner container, which breaks when the socket is shared)
        "python", "-I", "-B", "-",
    ]


async def run_code(code: str, wall_seconds: int) -> RunResult:
    wall = max(1, min(wall_seconds, MAX_WALL_SECONDS))
    args = _docker_args()
    loop = asyncio.get_running_loop()
    start = loop.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError:
        return RunResult(status="runner_error", notes=["docker CLI not available in the sandbox runner"])
    try:
        out, err = await asyncio.wait_for(proc.communicate(code.encode()), timeout=wall + 2)
    except asyncio.TimeoutError:
        await _kill(args)
        return RunResult(status="timeout", duration_ms=(loop.time() - start) * 1000,
                         notes=[f"killed after the {wall}s limit"])
    duration = (loop.time() - start) * 1000
    stdout, stderr = out.decode(errors="replace"), err.decode(errors="replace")
    network = any(s in stderr for s in ("Network is unreachable", "Temporary failure in name resolution",
                                        "Name or service not known", "No route to host"))
    # 137 = SIGKILL, which the OOM killer uses when the container exceeds --memory
    if proc.returncode == 137:
        return RunResult(status="oom", exit_code=137, stdout=stdout, stderr=stderr, duration_ms=duration,
                         network_attempted=network, notes=["container hit the memory limit and was killed"])
    status = "ok" if proc.returncode == 0 else "nonzero_exit"
    notes = ["code tried to use the network, which is blocked"] if network else []
    return RunResult(status=status, exit_code=proc.returncode, stdout=stdout, stderr=stderr,
                     duration_ms=duration, network_attempted=network, notes=notes)


async def _kill(args: list[str]) -> None:
    name = args[args.index("--name") + 1]
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", name, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(proc.wait(), timeout=5)
    except (FileNotFoundError, asyncio.TimeoutError):
        pass


# ---------------------------------------------------------------- HTTP service

app = FastAPI(title="MANDATE sandbox runner")


def require_secret(x_sandbox_secret: str | None = Header(default=None)) -> None:
    if x_sandbox_secret != SANDBOX_SECRET:
        raise HTTPException(401, "only the MANDATE gateway may use the sandbox")


class RunRequest(BaseModel):
    code: str = Field(max_length=100_000)
    wall_seconds: int = MAX_WALL_SECONDS


@app.get("/health")
async def health() -> dict:
    ok = False
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "version", "--format", "{{.Server.Version}}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        ok = proc.returncode == 0
    except (FileNotFoundError, asyncio.TimeoutError):
        ok = False
    return {"status": "ok", "docker": ok, "image": SANDBOX_IMAGE}


@app.post("/run", dependencies=[Depends(require_secret)])
async def run(req: RunRequest) -> dict:
    result = await run_code(req.code, req.wall_seconds)
    return result.public()
