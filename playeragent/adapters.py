from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


DEFAULT_BASE_URL = "https://router.shengsuanyun.com/api/v1"
DEFAULT_MODEL = "ali/qwen3.5-flash"


class ModelAdapter(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> str:
        """Return assistant content for a chat-completion style request."""


@dataclass(slots=True)
class ChatCompletionClient:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = 45.0

    async def complete(self, messages: list[dict[str, str]]) -> str:
        return await asyncio.to_thread(self._complete_sync, messages)

    def _complete_sync(self, messages: list[dict[str, str]]) -> str:
        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "temperature": 0.4,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM request failed with HTTP {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc.reason}") from exc
        return payload["choices"][0]["message"]["content"]
