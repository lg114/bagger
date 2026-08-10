"""Phase-1 structured memory extraction for bagger.

Turns raw conversation events into reusable ``memory_record`` rows via an LLM.
The LLM backend is pluggable: one OpenAI-compatible client covers every
domestic Chinese provider (智谱 GLM / DeepSeek / 阿里百炼 / 硅基流动 / 火山 /
Kimi) plus OpenAI itself — only ``base_url`` / ``api_key`` / ``model`` change.
"""

from bagger.consolidation.consolidator import Consolidator
from bagger.consolidation.llm_client import (
    LLMClient,
    MockLLMClient,
    OpenAICompatibleClient,
    create_llm_client,
)
from bagger.consolidation.models import MemoryRecord, MemoryType

__all__ = [
    "Consolidator",
    "LLMClient",
    "MockLLMClient",
    "OpenAICompatibleClient",
    "create_llm_client",
    "MemoryRecord",
    "MemoryType",
]
