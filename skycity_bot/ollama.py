from __future__ import annotations

from typing import Any, Sequence

import aiohttp


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, chat_model: str, embedding_model: str):
        self._base_url = base_url.rstrip("/")
        self._chat_model = chat_model
        self._embedding_model = embedding_model

    async def chat(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._chat_model,
            "messages": list(messages),
            "stream": False,
            "options": {"temperature": 0.1},
        }
        if tools:
            payload["tools"] = list(tools)

        response = await self._post("/api/chat", payload)
        message = response.get("message")
        if not isinstance(message, dict):
            raise OllamaError("Ollama 回應缺少 message")
        return message

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._post(
            "/api/embed",
            {"model": self._embedding_model, "input": list(texts)},
        )
        embeddings = response.get("embeddings")
        if not isinstance(embeddings, list):
            raise OllamaError("Ollama 回應缺少 embeddings")
        return embeddings

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=300)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self._base_url}{path}", json=payload) as response:
                    body = await response.text()
                    if response.status >= 400:
                        raise OllamaError(f"Ollama {response.status}: {body}")
                    return await response.json()
        except aiohttp.ClientError as error:
            raise OllamaError(f"無法連線至 Ollama：{error}") from error
