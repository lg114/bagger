"""LLM client abstraction for memory consolidation.

Design goal: the ``Consolidator`` depends only on the ``LLMClient`` Protocol,
never on a concrete backend. A single ``OpenAICompatibleClient`` covers every
OpenAI-compatible endpoint — which, conveniently, is *all* the domestic Chinese
providers (智谱 GLM, DeepSeek, 阿里百炼, 硅基流动, 火山, Kimi) plus OpenAI
itself. Switching provider is a config change (``base_url`` / ``api_key`` /
``model``), not a code change.

We use the stdlib ``urllib.request`` (no extra dependency) and default to JSON
mode (``response_format={"type":"json_object"}``) — the widest common
denominator across those providers, avoiding schema-negotiation failures on
smaller models.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Protocol, runtime_checkable

from bagger.config import settings


@runtime_checkable
class LLMClient(Protocol):
    """Anything the Consolidator can call to extract memory records."""

    def extract(
        self,
        system_prompt: str,
        user_content: str,
        response_schema: dict,
    ) -> list[dict]:
        """Return a list of record dicts with keys:
        ``type``, ``content``, ``topics`` (list[str]), ``confidence`` (float),
        ``event_id`` (str | None).
        """
        ...


class OpenAICompatibleClient:
    """Talks to any ``/v1/chat/completions`` endpoint via urllib (stdlib only)."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float = 60.0,
        use_json_schema: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.use_json_schema = use_json_schema

    def extract(
        self,
        system_prompt: str,
        user_content: str,
        response_schema: dict,
    ) -> list[dict]:
        if not self.api_key:
            raise RuntimeError(
                "No LLM API key configured. Set BAGGER_LLM_API_KEY or llm_api_key "
                "in ~/.bagger/config.toml."
            )

        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        }
        if self.use_json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "memory_records", "schema": response_schema},
            }
        else:
            body["response_format"] = {"type": "json_object"}

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"LLM API error {e.code}: {detail}") from e

        content = payload["choices"][0]["message"]["content"]
        data = json.loads(content)
        if not isinstance(data, dict):
            return []
        return data.get("records", [])


class MockLLMClient:
    """Deterministic stand-in that returns a couple of records derived from the
    chunk text, so the full pipeline can be exercised with zero network calls.
    """

    def extract(
        self,
        system_prompt: str,
        user_content: str,
        response_schema: dict,
    ) -> list[dict]:
        first_user = ""
        for line in user_content.splitlines():
            if line.startswith("[user") and "]" in line:
                first_user = line.split("] ", 1)[-1][:80]
                break
        return [
            {
                "type": "fact",
                "content": f"[mock] 会话片段提及: {first_user or '(空)'}",
                "topics": ["mock", "smoke-test"],
                "confidence": 0.6,
                "event_id": None,
            },
            {
                "type": "decision",
                "content": "[mock] 用于验证流水线的占位 decision 记录",
                "topics": ["mock"],
                "confidence": 0.5,
                "event_id": None,
            },
        ]


def create_llm_client(
    kind: str = "openai",
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    use_json_schema: bool = False,
) -> LLMClient:
    """Build an LLM client.

    Resolution order for each setting: explicit arg → ``BAGGER_LLM_*`` env var →
    ``settings.llm_*`` (config.toml). ``kind="mock"`` returns the offline
    stand-in regardless of credentials.
    """
    if kind == "mock":
        return MockLLMClient()

    base_url = base_url or os.environ.get("BAGGER_LLM_BASE_URL") or settings.llm_base_url
    api_key = (
        api_key
        or os.environ.get("BAGGER_LLM_API_KEY")
        or settings.llm_api_key
    )
    model = model or os.environ.get("BAGGER_LLM_MODEL") or settings.llm_model
    return OpenAICompatibleClient(
        base_url, api_key, model, use_json_schema=use_json_schema
    )
