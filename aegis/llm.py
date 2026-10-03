"""Model backends behind the gateway: the main OpenAI-compatible server and a deterministic mock."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


@dataclass
class Completion:
    content: str
    prompt_tokens: int
    completion_tokens: int


class LLMError(Exception):
    pass


async def complete(model: str, messages: list[dict], max_tokens: int,
                   timeout: float = 120.0, providers: dict[str, tuple[str, str]] | None = None,
                   extra_body: dict | None = None) -> Completion:
    provider, _, name = model.partition("/")
    prompt_text = "\n".join(str(m.get("content", "")) for m in messages)
    if provider == "mock":
        await asyncio.sleep(0.05)  # gives the budget simulator realistic overlap
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        content = f"[mock:{name}] Acknowledged: {str(last)[:160]}"
        completion = min(max_tokens, estimate_tokens(content))
        return Completion(content, estimate_tokens(prompt_text), completion)
    if providers and provider in providers:
        base_url, api_key = providers[provider]
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # OpenAI chat format has no "tool" role without tool_call_id: pass tool output as a labelled user turn
        msgs = [m if m.get("role") != "tool" else {"role": "user", "content": f"[tool result]\n{m['content']}"}
                for m in messages]
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{base_url}/chat/completions", headers=headers,
                                         json={"model": name, "messages": msgs, "max_tokens": max_tokens, **(extra_body or {})})
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"{provider} unavailable: {type(exc).__name__}") from exc
        usage = data.get("usage") or {}
        content = data["choices"][0]["message"].get("content") or ""
        return Completion(content, usage.get("prompt_tokens") or estimate_tokens(prompt_text),
                          usage.get("completion_tokens") or estimate_tokens(content))
    raise LLMError(f"model provider '{provider}' is not configured")
