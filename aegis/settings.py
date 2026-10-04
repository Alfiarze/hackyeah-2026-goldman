import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(os.environ.get("AEGIS_ROOT", Path(__file__).resolve().parent.parent))


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
    tools_base_url: str = os.environ.get("TOOLS_BASE_URL", "http://localhost:8001")
    tool_backend_secret: str = os.environ.get("TOOL_BACKEND_SECRET", "dev-backend-secret")
    sandbox_base_url: str = os.environ.get("SANDBOX_BASE_URL", "http://localhost:8002")
    sandbox_secret: str = os.environ.get("SANDBOX_SECRET", "dev-sandbox-secret")
    admin_api_key: str = os.environ.get("ADMIN_API_KEY", "hackyeah")
    app_api_key: str = os.environ.get("APP_API_KEY", "dev-app-key")
    lease_secret: str = os.environ.get("LEASE_SECRET", "dev-lease-secret")
    # agent api key -> agent id
    agent_keys: dict[str, str] = field(
        default_factory=lambda: _pairs(
            os.environ.get("AGENT_KEYS", "agent-key-demo:demo-agent,agent-key-other:other-agent")
        )
    )
    # Main model server, any OpenAI-compatible API. Testing: OpenRouter. Production: the team's GB10
    # (vLLM / SGLang / llama.cpp). Switching = changing these four variables, nothing else.
    llm_base_url: str = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    llm_api_key: str = os.environ.get("LLM_API_KEY", "")
    llm_model: str = os.environ.get("LLM_MODEL", "deepseek/deepseek-v4.1-flash")
    llm_location: str = os.environ.get("LLM_LOCATION", "onprem")  # onprem | cloud (data-flow sink)
    # extra JSON merged into every request, e.g. {"reasoning": {"enabled": false}} on OpenRouter so a reasoning
    # model does not spend the whole token budget thinking; vLLM/SGLang use their own switches
    llm_extra_body: dict = field(default_factory=lambda: json.loads(
        os.environ.get("LLM_EXTRA_BODY")
        or ('{"reasoning": {"enabled": false}}' if "openrouter.ai" in os.environ.get("LLM_BASE_URL", "openrouter.ai")
            else "{}")))
    poll_interval: float = float(os.environ.get("POLICY_POLL_SECONDS", "1.0"))
    background_tasks: bool = True

    @property
    def main_configured(self) -> bool:
        # OpenRouter needs a key; a self-hosted server (GB10) may run without one
        return bool(self.llm_base_url) and (bool(self.llm_api_key) or "openrouter.ai" not in self.llm_base_url)

    @property
    def providers(self) -> dict[str, tuple[str, str]]:
        return {"main": (self.llm_base_url, self.llm_api_key)} if self.main_configured else {}

    @property
    def main_model_id(self) -> str:
        return f"main/{self.llm_model}"

    @property
    def dsn(self) -> str:
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")
