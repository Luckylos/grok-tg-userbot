"""Grok API client - OpenAI-compatible via grok2api"""

import json
import asyncio
from typing import AsyncIterator

import httpx

from bot.config import config


class GrokStreamChunk:
    """A single chunk from the stream."""

    __slots__ = ("content", "reasoning_content", "finish_reason", "annotations",
                 "search_sources", "model", "usage")

    def __init__(self):
        self.content: str = ""
        self.reasoning_content: str = ""
        self.finish_reason: str | None = None
        self.annotations: list[dict] = []
        self.search_sources: list[dict] = []
        self.model: str = ""
        self.usage: dict | None = None


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if config.GROK_API_KEY:
        h["Authorization"] = f"Bearer {config.GROK_API_KEY}"
    return h


async def stream_chat(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.8,
    deepsearch: str | None = None,
    reasoning_effort: str | None = None,
    image_config: dict | None = None,
) -> AsyncIterator[GrokStreamChunk]:
    """Stream chat completions from grok2api. Yields GrokStreamChunk objects."""
    url = f"{config.GROK_API_BASE}/chat/completions"
    body: dict = {
        "model": model or config.GROK_MODEL,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": temperature,
    }
    if deepsearch:
        body["deepsearch"] = deepsearch
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    if image_config:
        body["image_config"] = image_config

    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream("POST", url, json=body, headers=_headers()) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    return
                try:
                    chunk_json = json.loads(data)
                except json.JSONDecodeError:
                    continue

                choice = chunk_json.get("choices", [{}])[0]
                delta = choice.get("delta", {})

                out = GrokStreamChunk()
                out.content = delta.get("content", "") or ""
                out.reasoning_content = delta.get("reasoning_content", "") or ""
                out.finish_reason = choice.get("finish_reason")
                out.model = chunk_json.get("model", "")

                if "annotations" in chunk_json:
                    out.annotations = chunk_json["annotations"]
                if "search_sources" in chunk_json:
                    out.search_sources = chunk_json["search_sources"]
                if chunk_json.get("usage"):
                    out.usage = chunk_json["usage"]

                yield out


async def generate_image(
    prompt: str,
    model: str = "grok-imagine-image",
    n: int = 1,
    size: str = "1024x1024",
    response_format: str = "url",
) -> dict:
    """Generate image via grok2api /v1/images/generations."""
    url = f"{config.GROK_API_BASE}/images/generations"
    body = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "size": size,
        "response_format": response_format,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=body, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def list_models() -> list[dict]:
    """List available models."""
    url = f"{config.GROK_API_BASE}/models"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])
