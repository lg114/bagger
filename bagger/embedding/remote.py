"""Remote embedding via any OpenAI-compatible ``/embeddings`` endpoint.

Zero extra dependency: uses only the stdlib ``urllib`` (same choice as
``bagger.consolidation.llm_client``). Defaults point at 智谱 ``embedding-3``,
which is OpenAI-compatible and shares the consolidation LLM key — so no new
secret to provision. Swap ``base_url``/``model``/``api_key`` for OpenAI
``text-embedding-3-*``, DeepSeek, 硅基流动, etc.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from bagger.embedding.base import Embedder
from bagger.security import redact_secrets

# Remote endpoints accept batches; chunk to stay well under request-size limits.
REMOTE_BATCH = 64


class RemoteEmbedder(Embedder):
    """Talks to ``{base_url}/embeddings`` via urllib (stdlib only)."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float = 60.0,
        redact: bool | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model
        self.timeout = timeout
        from bagger.config import settings

        self.redact = settings.remote_redact_secrets if redact is None else redact
        self.dim: int = 0

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError(
                "No embedding API key configured. Set BAGGER_EMBEDDING_API_KEY or "
                "embedding_api_key in ~/.bagger/config.toml (falls back to the "
                "consolidation LLM key). Remote embedding cannot proceed."
            )
        if self.redact:
            texts = [redact_secrets(text) for text in texts]
        body = {"model": self.model_name, "input": texts}
        req = urllib.request.Request(
            f"{self.base_url}/embeddings",
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
            raise RuntimeError(f"Embedding API error {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Embedding API unreachable: {e.reason}") from e

        data = payload.get("data") or []
        if not data:
            raise RuntimeError("Embedding API returned an empty `data` array")
        vecs = [d["embedding"] for d in data]
        if self.dim == 0:
            self.dim = len(vecs[0])
        return vecs

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), REMOTE_BATCH):
            out.extend(self._embed(texts[i : i + REMOTE_BATCH]))
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]
