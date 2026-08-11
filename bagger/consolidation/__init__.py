"""Phase-1 structured memory extraction and consolidation for bagger.

Turns raw conversation events into reusable ``memory_record`` rows via an LLM,
then keeps that corpus free of duplicates. The LLM backend is pluggable: one
OpenAI-compatible client covers every domestic Chinese provider (智谱 GLM /
DeepSeek / 阿里百炼 / 硅基流动 / 火山 / Kimi) plus OpenAI itself — only
``base_url`` / ``api_key`` / ``model`` change.

Module map::

    normalize.py   near-duplicate detection (bigram Jaccard, clustering)
    validation.py  coerce untrusted LLM output into records + reject audit
    dedup.py       merge rules (pure); L0/L1/L2 policy
    llm_client.py  transport, error classification, backoff
    consolidator.py  the pipeline: fetch -> extract -> validate -> upsert
    errors.py      retryable vs terminal failure taxonomy
"""

from bagger.consolidation.consolidator import Consolidator
from bagger.consolidation.errors import (
    ConsolidationError,
    LLMResponseError,
    LLMTransportError,
    LLMUnauthorizedError,
)
from bagger.consolidation.llm_client import (
    LLMClient,
    MockLLMClient,
    OpenAICompatibleClient,
    create_llm_client,
)
from bagger.consolidation.models import (
    ChunkFailure,
    ConsolidationReport,
    DedupReport,
    MemoryRecord,
    MemoryType,
    MergeCluster,
    ProgressEvent,
    RejectedRecord,
    RejectReason,
)
from bagger.consolidation.normalize import DEFAULT_FUZZY_THRESHOLD
from bagger.consolidation.validation import coerce_records

__all__ = [
    "DEFAULT_FUZZY_THRESHOLD",
    "ChunkFailure",
    "ConsolidationError",
    "ConsolidationReport",
    "Consolidator",
    "DedupReport",
    "LLMClient",
    "LLMResponseError",
    "LLMTransportError",
    "LLMUnauthorizedError",
    "MemoryRecord",
    "MemoryType",
    "MergeCluster",
    "MockLLMClient",
    "OpenAICompatibleClient",
    "ProgressEvent",
    "RejectReason",
    "RejectedRecord",
    "coerce_records",
    "create_llm_client",
]
