import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(os.environ.get("MANDATE_ROOT", Path(__file__).resolve().parent.parent))


def _pairs(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in filter(None, (p.strip() for p in raw.split(","))):
        key, _, value = item.partition(":")
        out[key] = value
    return out


@dataclass
class Settings:
    database_url: str = os.environ.get(
        "DATABASE_URL", "postgresql://goldman:goldman@localhost:5432/goldman"
    )
    policy_path: Path = Path(os.environ.get("POLICY_PATH", ROOT / "policy" / "policy.yaml"))
    feed_path: Path = Path(os.environ.get("ATTACK_FEED_PATH", ROOT / "feeds" / "attacks.yaml"))
    feed_url: str | None = os.environ.get("ATTACK_FEED_URL") or None
    ollama_base_url: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    tools_base_url: str = os.environ.get("TOOLS_BASE_URL", "http://localhost:8001")
    tool_backend_secret: str = os.environ.get("TOOL_BACKEND_SECRET", "dev-backend-secret")
    admin_api_key: str = os.environ.get("ADMIN_API_KEY", "dev-admin-key")
    app_api_key: str = os.environ.get("APP_API_KEY", "dev-app-key")
    lease_secret: str = os.environ.get("LEASE_SECRET", "dev-lease-secret")
    # agent api key -> agent id
    agent_keys: dict[str, str] = field(
        default_factory=lambda: _pairs(
            os.environ.get("AGENT_KEYS", "agent-key-demo:demo-agent,agent-key-other:other-agent")
        )
    )
    poll_interval: float = float(os.environ.get("POLICY_POLL_SECONDS", "1.0"))
    background_tasks: bool = True

    @property
    def dsn(self) -> str:
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")
