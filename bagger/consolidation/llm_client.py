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

**Failure handling is the production-critical part.** A run over 60+ sessions
issues hundreds of requests; rate limits and transient 5xx are certainties, not
edge cases. Every failure is therefore classified at the point where the status
code is actually known (see :mod:`bagger.consolidation.errors`) and only the
retryable class is retried, with exponential backoff and jitter. An invalid API
key fails on the first attempt instead of burning three retries per chunk.
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from bagger.config import settings
from bagger.security import redact_secrets
from bagger.consolidation.errors import (
    LLMResponseError,
    LLMTransportError,
    LLMUnauthorizedError,
)

__all__ = [
    "LLMClient",
    "MockLLMClient",
    "OpenAICompatibleClient",
    "create_llm_client",
]

# Status codes worth trying again: rate limiting, request timeout, and the 5xx
# family. Everything else in 4xx is a client-side mistake that a retry repeats.
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})


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


def _strip_code_fence(text: str) -> str:
    """Remove a markdown code fence the model wrapped around its JSON.

    JSON mode is meant to prevent this, but smaller models — exactly the free
    ones this project defaults to — still emit ```json ... ``` often enough
    that discarding the response over it would be wasteful.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped.split("\n", 1)[-1] if "\n" in stripped else ""
    if body.rstrip().endswith("```"):
        body = body.rstrip()[: -len("```")]
    return body.strip()


def _records_from_payload(data: object) -> list[dict]:
    """Pull the record list out of whatever shape the model returned.

    Accepts the documented ``{"records": [...]}``, a bare top-level list, and
    the common ``{"memories"/"items"/"data": [...]}`` near-misses. Anything else
    is a response error.
    """
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("records", "memories", "items", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        # A single record returned unwrapped.
        if "content" in data and ("type" in data or "kind" in data):
            return [data]
        return []
    raise LLMResponseError(f"expected a JSON object or array, got {type(data).__name__}")


class OpenAICompatibleClient:
    """Talks to any ``/v1/chat/completions`` endpoint via urllib (stdlib only)."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float = 60.0,
        use_json_schema: bool = False,
        max_retries: int = 3,
        backoff_base: float = 1.5,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.use_json_schema = use_json_schema
        # ``max_retries`` counts *additional* attempts after the first.
        self.max_retries = max(0, max_retries)
        self.backoff_base = backoff_base
        # Injected so tests exercise the retry path without real delays.
        self._sleep = sleep

    # -- request plumbing -------------------------------------------

    def _build_body(self, system_prompt: str, user_content: str, response_schema: dict) -> dict:
        if settings.remote_redact_secrets:
            user_content = redact_secrets(user_content)
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
        return body

    def _post(self, body: dict) -> dict:
        """One HTTP round trip. Raises a classified error, never a bare one."""
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
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            if e.code in _RETRYABLE_STATUS:
                raise LLMTransportError(f"LLM API {e.code}: {detail}", status=e.code) from e
            raise LLMUnauthorizedError(f"LLM API {e.code}: {detail}", status=e.code) from e
        except urllib.error.URLError as e:
            raise LLMTransportError(f"LLM API unreachable: {e.reason}") from e
        except TimeoutError as e:
            raise LLMTransportError(f"LLM API timed out after {self.timeout}s") from e

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise LLMResponseError(f"response body is not JSON: {raw[:200]}") from e
        if not isinstance(payload, dict):
            raise LLMResponseError(f"expected an object envelope, got {type(payload).__name__}")
        return payload

    def extract(
        self,
        system_prompt: str,
        user_content: str,
        response_schema: dict,
    ) -> list[dict]:
        if not self.api_key:
            raise LLMUnauthorizedError(
                "No LLM API key configured. Set BAGGER_LLM_API_KEY or llm_api_key "
                "in ~/.bagger/config.toml."
            )

        body = self._build_body(system_prompt, user_content, response_schema)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                payload = self._post(body)
                break
            except LLMTransportError as e:
                last_error = e
                if attempt >= self.max_retries:
                    raise
                # Exponential backoff with jitter: without jitter, several
                # chunks rate-limited at the same instant would retry in
                # lockstep and trip the limit again.
                delay = self.backoff_base**attempt * (1.0 + random.random() * 0.3)  # noqa: S311
                self._sleep(delay)
        else:  # pragma: no cover - loop always breaks or raises
            raise last_error or LLMTransportError("LLM request failed")

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMResponseError(f"malformed completion envelope: {str(payload)[:200]}") from e

        try:
            data = json.loads(_strip_code_fence(content or ""))
        except json.JSONDecodeError as e:
            raise LLMResponseError(f"model did not return JSON: {(content or '')[:200]}") from e
        return _records_from_payload(data)


class MockLLMClient:
    """Deterministic stand-in that returns a couple of records derived from the
    chunk text, so the full pipeline can be exercised with zero network calls.

    Records are derived from the chunk's first user line, which means two
    different chunks yield different content — otherwise every chunk would
    produce the same fingerprint and the mock would exercise only the merge
    path, never the insert path.
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
    max_retries: int = 3,
) -> LLMClient:
    """Build an LLM client.

    Resolution order for each setting: explicit arg → ``BAGGER_LLM_*`` env var →
    ``settings.llm_*`` (config.toml). ``kind="mock"`` returns the offline
    stand-in regardless of credentials.
    """
    if kind == "mock":
        return MockLLMClient()

    base_url = base_url or os.environ.get("BAGGER_LLM_BASE_URL") or settings.llm_base_url
    api_key = api_key or os.environ.get("BAGGER_LLM_API_KEY") or settings.llm_api_key
    model = model or os.environ.get("BAGGER_LLM_MODEL") or settings.llm_model
    return OpenAICompatibleClient(
        base_url,
        api_key,
        model,
        use_json_schema=use_json_schema,
        max_retries=max_retries,
    )
