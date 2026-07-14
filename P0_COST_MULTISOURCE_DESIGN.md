# bagger P0 设计文档：成本抓取 + 多源 Usage 归一化

> 状态：设计稿（未实施） ｜ 提出日期：2026-07-14 ｜ 范围：P0（数据完整性 + 多源基础）
> 背景：用户（gc）在做 memorized（AI Agent 长期记忆运行时），bagger 是其「采集层」。讨论聚焦于「非 Anthropic 后端（如小米 MiMo）下如何可信地计算成本」。

---

## 0. 背景

### 0.1 现状（已核实）
- `parser/claude.py` 仅提取 `input_tokens` + `output_tokens`，全项目对 `cost` / `cache` / `service_tier` 的引用为 0。
- `models/event.py` 的 `MemoryEvent` 只有 `token_input` / `token_output`，无成本 / 缓存 / 模型字段。
- `storage/sqlite.py` 的 `get_stats` 用 `SUM(token_input + token_output)` 当总量，无成本维度。
- 多源仅注册 `ClaudeParser`，`scan` / `watch` 未暴露 `--source`。
- `model` 字段未存入事件、未用于定价或 per-model 统计。

### 0.2 痛点
1. **永远算不出钱**：Claude Code transcript 自带 `cost_usd` / `cache_*` / `service_tier`，bagger 全丢了。
2. **非 Anthropic 后端不可信**：换 MiMo / DeepSeek / 本地模型后，`cost_usd` 要么为 0、要么假价、要么不存在（Claude Code 按 Anthropic 内置价目表乘，不认识非 Anthropic 模型名时算 0 或乱填）。
3. **中转伪装**：为让 Claude Code 跑通非 Anthropic 后端，常把 model 伪装成 `claude-sonnet-4-*`，transcript 无法反映真实后端。
4. **统计失真风险**：若简单把未知成本填 0，会静默低估总成本（假数据比没数据更危险）。

### 0.3 目标
- bagger 能从 transcript 抓取完整 usage（含成本 / 缓存），并在多源下保持数据可信。
- 不依赖「transcript 自带 `cost_usd` 一定可信」的假设。
- 简单（用户不必为每个提供商维护价目表）与诚实（不伪造成本）兼得。

---

## 1. 设计原则（宪法）

| 原则 | 含义 |
|---|---|
| **不假设 cost_usd 可信** | 仅当它 >0 且来源为直连 Anthropic 时才直接采用 |
| **NULL 优先** | cost 默认存 `NULL`（未知），`0` 仅用于表示真免费（本地 / 包月） |
| **统计分两线** | 已计价成本 与 未计价用量 分开呈现，绝不混加 |
| **parser 归一化 usage** | 各 provider 的 usage schema 不同，parser 统一映射为 bagger 标准字段 |
| **model / provider 显式捕获** | 存 model 字段；中转伪装场景用 config 声明真实 provider |
| **可选内置默认价** | 常见模型随包内置价目表，减轻用户维护负担（增强项，非必做） |

---

## 2. 标准 Usage 模型（parser 归一化目标）

bagger 内部统一使用以下标准字段，与具体 provider 解耦：

```
token_input       : int         # 全新输入
token_output      : int         # 输出
token_cache_read  : int         # 命中缓存读
token_cache_write : int         # 新建缓存
cost_usd          : float|None  # 已计价成本（统一折算价，见 §5 币种）
currency          : str         # 成本币种
service_tier      : str|None
model             : str|None    # transcript 中的 model 名
provider          : str|None    # 真实后端（经映射推断，见 §4.3）
```

各 provider → 标准字段的映射由对应 Parser 负责：
- **Anthropic / Claude Code**：`cache_creation_input_tokens` → `token_cache_write`，`cache_read_input_tokens` → `token_cache_read`，`cost_usd` 直接采用（>0）。
- **OpenAI 兼容**：`prompt_tokens`→input，`completion_tokens`→output，无 cache 字段则留 0，无 cost 则 NULL。
- **本地 / 未知**：尽力取 token 数，cost = NULL（或用户声明为 0）。

---

## 3. 数据模型改动（models/event.py）

`MemoryEvent` 新增 / 调整字段：

```python
class MemoryEvent(BaseModel):
    # —— 现有 ——
    token_input: int = 0
    token_output: int = 0
    # —— 新增 ——
    token_cache_read: int = 0
    token_cache_write: int = 0
    cost_usd: float | None = None    # NULL 优先
    currency: str = "USD"
    service_tier: str | None = None
    model: str | None = None         # transcript 中的 model
    provider: str | None = None      # 真实后端（映射后）
```

> `cost_usd=None` 与 `cost_usd=0.0` 语义不同：前者 = 未知，后者 = 真免费。

---

## 4. Parser 改动（parser/base.py + claude.py）

### 4.1 Parser ABC 增加归一化契约
```python
class Parser(ABC):
    @abstractmethod
    def normalize_usage(self, raw_usage: dict, raw_model: str | None) -> StandardUsage:
        """把 provider 原始 usage 映射为 §2 标准字段"""
```

### 4.2 ClaudeParser 取值优先级链
```python
def normalize_usage(self, raw, model):
    cost = None
    if raw.get("cost_usd", 0) > 0:
        cost = raw["cost_usd"]                 # ① transcript 自带且可信
    elif (pricing := pricing_lookup(model)):
        cost = compute(raw, pricing)           # ② 价目表（用户或内置）
    # 否则保持 None —— 绝不填 0
    return StandardUsage(
        token_input=raw.get("input_tokens", 0),
        token_output=raw.get("output_tokens", 0),
        token_cache_read=raw.get("cache_read_input_tokens", 0),
        token_cache_write=raw.get("cache_creation_input_tokens", 0),
        cost_usd=cost, currency="USD",
        service_tier=raw.get("service_tier"),
        model=model, provider=resolve_provider(model),
    )
```

### 4.3 provider 解析与映射（解决中转伪装）
`resolve_provider(model)` 逻辑：
1. 若 model 命中 `config.source_alias`（用户声明的 伪装名 → 真实 provider），返回声明的 provider。
2. 否则用内置前缀表推断（`claude-*`→anthropic，`xiaomi/*`→xiaomi，等）。
3. 兜底 `unknown`。

---

## 5. 配置层（config.py + config.toml）

### 5.1 价目表（带币种）
```toml
[pricing.claude-sonnet-4]
currency = "USD"
input_per_mtok  = 3.0
output_per_mtok = 15.0
cache_write_per_mtok = 3.75
cache_read_per_mtok  = 0.30

[pricing.xiaomi-mimo]
currency = "CNY"
input_per_mtok  = 1.0
output_per_mtok = 2.0
cache_write_per_mtok = 0.0
cache_read_per_mtok  = 0.0
```
> 填的是你实际用的后端真实单价（来源：服务商官网计费页）。直连 Anthropic 时可不填——transcript 自带 `cost_usd`。

### 5.2 中转伪装映射
```toml
[[source_alias]]
match_model = "claude-sonnet-4-*"
actual_provider = "xiaomi-mimo"
```
> 用途：transcript 里看着是 `claude-sonnet-4-*` 的会话，实际后端是 MiMo，成本按 MiMo 价目表计。

### 5.3 币种处理
- 每条 cost 记录带 `currency`。
- 统计时统一折算：建议内部以 USD 为锚，config 提供 `fx_rates`（或默认 1:1 仅做标注）。
- 未配置 fx 时，分币种分别汇总，不强行跨币种加总（避免假账）。

---

## 6. 存储层（storage/sqlite.py）

### 6.1 schema 扩展（迁移）
```sql
ALTER TABLE events ADD COLUMN token_cache_read  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE events ADD COLUMN token_cache_write INTEGER NOT NULL DEFAULT 0;
ALTER TABLE events ADD COLUMN cost_usd          REAL;            -- 允许 NULL
ALTER TABLE events ADD COLUMN currency          TEXT NOT NULL DEFAULT 'USD';
ALTER TABLE events ADD COLUMN service_tier      TEXT;
ALTER TABLE events ADD COLUMN model             TEXT;
ALTER TABLE events ADD COLUMN provider          TEXT;
```
> 通过 `PRAGMA user_version` 从 1 → 2 触发迁移；首次打开旧库时执行上述 ALTER（项目当前无迁移框架，本设计顺带建立最小迁移机制）。

### 6.2 get_stats 改算（分两线）
```sql
-- 线 A：已计价成本
SELECT COALESCE(SUM(cost_usd), 0) AS billed_cost
FROM events WHERE cost_usd IS NOT NULL;

-- 线 B：未计价用量（按 provider 聚合）
SELECT provider,
       COALESCE(SUM(token_input + token_output), 0) AS unbilled_tokens
FROM events WHERE cost_usd IS NULL
GROUP BY provider;

-- 缓存命中率（已有 cache 字段后可得）
SELECT SUM(token_cache_read) * 1.0
       / NULLIF(SUM(token_cache_read + token_cache_write + token_input), 0)
FROM events;
```

---

## 7. API / 统计返回结构

```json
{
  "billed_cost": { "USD": 3.21, "CNY": 0.0 },
  "unbilled": [
    { "provider": "xiaomi-mimo", "tokens": 128000, "note": "成本未配置" }
  ],
  "cache_hit_rate": 0.71,
  "per_provider": [ "..." ],
  "per_model": [ "..." ]
}
```

---

## 8. 实施任务清单

| # | 任务 | 文件 | 必做 / 可选 |
|---|---|---|---|
| 1 | MemoryEvent 加 7 个字段 | models/event.py | 必做 |
| 2 | Parser ABC 加 normalize_usage | parser/base.py | 必做 |
| 3 | ClaudeParser 实现归一化 + 取值链 | parser/claude.py | 必做 |
| 4 | resolve_provider + 映射逻辑 | parser/__init__.py 或新 pricing.py | 必做 |
| 5 | events 表迁移（user_version 1→2） | storage/sqlite.py | 必做 |
| 6 | get_stats 改算两线 + 缓存率 | storage/sqlite.py | 必做 |
| 7 | config 价目表 + source_alias 解析 | config.py | 必做 |
| 8 | /api/stats 返回新结构 | api/app.py + services | 必做 |
| 9 | 内置默认价目表（常见模型） | pricing.py | 可选 |
| 10 | 前端成本 / 未计价展示 | ui/ | 可选 |
| 11 | 密钥脱敏（顺带 P0 安全项） | parser/claude.py | 建议 |

---

## 9. 风险与边界

- **中转伪装无声明**：若用户不配 `source_alias`，bagger 会把伪装名当真名，成本仍可能错位 → 文档需引导用户配置。
- **币种折算**：未配 fx 时不可强行跨币种加总，否则制造假账。
- **内置价目表维护**：增强项，需随厂商调价更新；可标记 `as_of` 日期提示过期。
- **subagent / 分支**：本设计聚焦 cost / 多源，subagent 会话纳入、分支回放为独立 P0 项，不在此文档范围（见 gap 分析）。

---

## 10. 验收标准

- [ ] 直连 Anthropic 会话：cost / cache 正确入库，统计准确。
- [ ] 非 Anthropic（MiMo）会话：transcript 无 cost_usd 时，按 config 价目表算出成本；未配置时 cost = NULL 且不污染总额。
- [ ] `get_stats` 返回的 billed_cost 与 unbilled 分开，currency 正确。
- [ ] 旧库升级走迁移，user_version = 2，无数据丢失。
- [ ] 新增单测覆盖：取值优先级链、NULL vs 0、伪装映射、迁移。
