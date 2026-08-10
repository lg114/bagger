"""Prompts + response schema for memory extraction.

The system prompt encodes *what is worth remembering* — the single most
important design decision in phase 1, because it defines the quality bar. It
also embeds one few-shot example so the model sees the exact output shape.
"""

from __future__ import annotations

import json

SYSTEM_PROMPT = """你是一个"长期记忆提炼器"。你的任务是从一段 AI 编程助手的对话片段中，\
提炼出**可复用、跨会话有意义**的认知单元（memory records）。

提炼原则：
- 只提取值得"记住"的内容，忽略寒暄、临时状态、一次性报错、工具调用噪音。
- 每条记录要自包含、可独立理解，像一条笔记。要提炼，不要照搬原文。
- 用第三人称、客观陈述（"gc 决定用 Zvec 替代 Chroma"而非"我决定…"）。
- 给 1-4 个 topics 关键词，便于日后按主题检索，中文优先。
- confidence 是你对该提炼准确性的把握（0-1）。不确定就给低分。
- event_id 填这条记录主要源自哪条事件（从输入里带 (事件编号) 的行选），没有就留空。

四类记录：
- fact（事实）：客观已知信息，如"项目用 Zvec 做向量存储"。
- preference（偏好）：习惯/口味，如"gc 偏好本地优先方案"。
- decision（决定）：做出的选型/结论，如"将向量存储从 Chroma 切换到 Zvec"。
- lesson（教训）：踩过的坑/经验，如"Chroma 在大数据量下查询延迟高"。

只输出一个 JSON 对象，不要任何额外文字或 markdown 代码块。格式示例：

{
  "records": [
    {
      "type": "decision",
      "content": "记忆向量存储从 Chroma 切换到 Zvec，理由是本地优先场景读取延迟更低",
      "topics": ["存储", "向量数据库", "选型"],
      "confidence": 0.9,
      "event_id": "a1b2c3d4"
    },
    {
      "type": "fact",
      "content": "Chroma 在现有项目里查询偏慢",
      "topics": ["存储", "性能"],
      "confidence": 0.7,
      "event_id": "a1b2c3d4"
    }
  ]
}
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["fact", "preference", "decision", "lesson"],
                    },
                    "content": {"type": "string"},
                    "topics": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "event_id": {"type": ["string", "null"]},
                },
                "required": ["type", "content", "topics", "confidence"],
            },
        }
    },
    "required": ["records"],
}

# Kept for documentation / potential json_schema-mode providers.
FEW_SHOT_EXAMPLE = {
    "input": "[user] 我们项目的向量存储一直用 Chroma，但感觉查询太慢了\n"
    "[assistant] 可以试试 Zvec，它在本地优先场景下的读取延迟低很多\n"
    "[user] 好，那就换成 Zvec 吧",
    "output": {
        "records": [
            {
                "type": "decision",
                "content": "记忆向量存储从 Chroma 切换到 Zvec，理由是本地优先场景读取延迟更低",
                "topics": ["存储", "向量数据库", "选型"],
                "confidence": 0.9,
                "event_id": "",
            },
            {
                "type": "fact",
                "content": "Chroma 在现有项目里查询偏慢",
                "topics": ["存储", "性能"],
                "confidence": 0.7,
                "event_id": "",
            },
        ]
    },
}

# Expose the example as a JSON string for callers that want to render it.
FEW_SHOT_JSON = json.dumps(FEW_SHOT_EXAMPLE, ensure_ascii=False)
