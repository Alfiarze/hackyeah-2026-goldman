"""Model backends behind the gateway: local Ollama and a deterministic mock."""

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


async def complete(model: str, messages: list[dict], max_tokens: int, ollama_base_url: str,
                   timeout: float = 120.0) -> Completion:
    provider, _, name = model.partition("/")
    prompt_text = "\n".join(str(m.get("content", "")) for m in messages)
    if provider == "mock":
        await asyncio.sleep(0.05)  # gives the budget simulator realistic overlap
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        content = f"[mock:{name}] Acknowledged: {str(last)[:160]}"
        completion = min(max_tokens, estimate_tokens(content))
        return Completion(content, estimate_tokens(prompt_text), completion)
    if provider == "ollama":
        payload = {"model": name, "messages": messages, "stream": False, "keep_alive": "30m",
                   "options": {"num_predict": max_tokens}}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{ollama_base_url.rstrip('/')}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"ollama unavailable: {type(exc).__name__}") from exc
        content = data["message"]["content"]
        return Completion(content, data.get("prompt_eval_count") or estimate_tokens(prompt_text),
                          data.get("eval_count") or estimate_tokens(content))
    raise LLMError(f"unknown provider '{provider}'")
