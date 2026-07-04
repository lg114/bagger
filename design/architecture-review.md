# bagger 架构评估报告

> 评估时间：2026-07-04 · 评估视角：软件架构师 · 评估对象：bagger v0.1.0

## 执行摘要

**健康度评级：B+** —— 分层清晰、意图良好，但正处在「单源脚本 → 多源平台」的拐点。

核心判断：**架构本身不烂，问题在于"还没来得及打开接缝"**。`models/event.py` 的注释写着 *"from any AI coding tool"*，`exporters/` 已经有 `base.py` 抽象——说明设计意图是平台化的，但 `parser/` 和 `storage/` 这两个最该有接缝的地方还停在具体实现上。现在投入小规模重构（打开四道接缝）能避免后续大改；拖到接入第二个数据源时再改，成本会翻倍。

- **6 个痛点**：2 个 P0（阻塞扩展）、3 个 P1（影响可维护性）、1 个 P2（性能体验）
- **4 道接缝**：Parser Protocol、Repository Protocol、SyncService、Settings
- **演进策略**：每道接缝都可独立落地，用适配器模式渐进迁移，不中断现有功能

---

## 一、现状架构：做得好的地方

先说结论里好的部分，这些是演进的资产，不是负担。

| # | 优点 | 证据 |
|---|------|------|
| 1 | **五层分层清晰，依赖方向单一向下** | `models → parser → storage → services → {cli, api}`，没有跨层回调 |
| 2 | **领域模型中立** | `MemoryEvent` 注释 "from any AI coding tool"，`Role`/`BlockType` 不绑定 Claude 私有结构 |
| 3 | **增量同步设计成熟** | `WatchState` 用 byte offset，scanner 全量+增量双模式，watcher 轮询复用 |
| 4 | **exporters 已有抽象基类** | `exporters/base.py` 定义协议，`jsonl.py` 是实现之一——这是 parser 该学的样子 |
| 5 | **API 用工厂函数 + 依赖注入雏形** | `create_app()` + `get_storage()` contextmanager，routes 按职责拆分 |
| 6 | **依赖分层 optional-dependencies** | `dev/web/bundle` 三组，桌面端 sidecar 打包路径干净 |
| 7 | **桌面端前后端解耦** | Tauri + sidecar exe，Python 后端独立可单跑 |

这些是地基。下面的痛点都是在地基上"还没搭接缝"的问题，不是地基本身有问题。

---

## 二、痛点清单（按优先级）

### P0-1 · Parser 无抽象基类

**现象**：`parser/` 下只有 `claude.py`，没有 `base.py`。`services/scanner.py` 直接 `from bagger.parser.claude import parse_jsonl`，硬编码 Claude 路径（`CLAUDE_PROJECTS_DIR`）。

**影响**：要接入 Cursor / Windsurf / Codex 等第二个数据源，必须改 `scanner.py` 和 `watcher.py` 两个文件，加 if-else 分支。这与 `exporters/base.py` 已有的抽象风格不一致——同一个项目里两套标准。

**Trade-off**：
- 现在抽象：多写一个 `Parser` Protocol + Registry，约 40 行
- 不抽象：每加一个数据源改 3 处（scanner/watcher/discover），且分支会指数增长

**建议**：引入 `parser/base.py` 定义 `Parser` 协议（`parse(path) -> list[MemoryEvent]` + `discover() -> list[Path]` + `source_name -> str`），用注册表分发。Claude parser 是第一个实现。

---

### P0-2 · SqliteStorage 上帝类 + 无 Repository 接口

**现象**：`storage/sqlite.py` 单类 528 行，承担：连接管理 + session CRUD + event CRUD + FTS5 搜索 + LIKE 搜索 + 分页 + 统计 + 完整性检查。`services/` 直接依赖 `SqliteStorage` 具体类。

**影响**：
1. 单类职责过多，修改统计逻辑要在一个 528 行文件里翻
2. services 依赖具体实现而非接口，测试只能用真实 SQLite，无法 mock
3. 未来要换 PostgreSQL 或加向量存储（用户的 memorized 项目方向），没有接缝可换

**Trade-off**：
- 拆分 + 抽接口：一次性投入，后续每次扩展受益
- 保持现状：短期省事，但每次加查询都要往这个类里塞

**建议**：定义 `Repository` 协议（拆 `SessionRepository` / `EventRepository` / `SearchIndex` 三个子接口），`SqliteStorage` 实现之。services 依赖协议而非具体类。**不必现在拆文件，先有接口即可**。

---

### P1-1 · scanner / watcher 逻辑重复

**现象**：`scanner.scan_all()` 和 `watcher.Watcher._poll()` 都做同一件事：discover → parse → insert → export → upsert session。`watcher.py` 还运行时 `from bagger.services.scanner import _parse_new_lines`（import 私有函数，下划线开头）。

**影响**：
1. 增量同步逻辑两份拷贝，修 bug 要改两处
2. watcher 依赖 scanner 的私有函数，封装泄漏
3. 未来加事件钩子（如"新事件通知"）要在两处加

**Trade-off**：
- 抽 `SyncService`：消除重复，但多一层间接
- 保持现状：重复但直白

**建议**：抽 `services/sync.py` 的 `SyncService`，封装"discover → parse → insert → export → upsert"流水线。scanner 和 watcher 只是触发器不同（一次性 vs 轮询），都调 SyncService。

---

### P1-2 · 配置散落 4 处

**现象**：
- `cli/main.py`：`BAGGER_DIR`、`DB_PATH`
- `api/dependencies.py`：`DB_PATH`（重复定义）
- `services/scanner.py`：`CLAUDE_PROJECTS_DIR`、`state_path` 默认值、`jsonl_path` 默认值
- `services/watcher.py`：`events.jsonl` 路径硬编码

同一个 `DB_PATH` 在两个文件里各定义一次，已经出现漂移风险。

**影响**：配置改一处要 grep 全项目；新用户无法通过配置文件自定义路径；环境变量覆盖无机制。

**Trade-off**：
- 引入 `pydantic-settings`：多一个依赖，但配置集中、可校验、可覆盖
- 保持散落：零依赖，但漂移风险持续累积

**建议**：新建 `bagger/config.py`，用 `pydantic-settings` 定义 `Settings`（db_path、claude_dir、state_path、jsonl_path、api_host/port）。所有层从 Settings 读取。

---

### P1-3 · tool 统计用字符串反解析

**现象**：`storage/sqlite.py` 的 `get_tool_usage_stats()`（L442）用 `SUBSTR(content_text, INSTR(content_text, '[tool_use:') + 10, ...)` 从 `[tool_use:xxx]` 文本标记里反解析工具名。

**影响**：
1. 把结构化数据（`ContentBlock.tool_name`）序列化进 `content_text`，再用字符串函数解析回来——脆弱，`[tool_use:` 格式一变就崩
2. 全表扫描 + 字符串函数，数据量大时慢
3. 无法统计 tool_input 参数分布

**Trade-off**：
- 建 `tool_uses` 表（event_id, tool_name, tool_id, tool_input_json）：结构化查询，但需迁移
- 保持字符串解析：零迁移，但脆弱且慢

**建议**：建 `tool_uses` 关联表，parser 写入时同步插入。统计改为 `SELECT tool_name, COUNT(*) FROM tool_uses GROUP BY tool_name`。旧数据写个一次性迁移脚本。

---

### P2-1 · CJK 搜索降级

**现象**：FTS5 `unicode61` tokenizer 不分词 CJK，中文查询回退到 `LIKE '%query%'` 全表扫描，无 BM25 ranking。代码注释自己承认 *"exhaustive but guarantees no misses"*。

**影响**：数据量上万条事件后，中文搜索明显变慢；无排序，结果质量低。

**Trade-off**：
- jieba 分词 + FTS5 自定义 tokenizer：中文体验好，但引入 jieba 依赖
- trigram tokenizer（SQLite 3.34+）：零依赖，但索引体积涨 3-5 倍
- 保持 LIKE：零成本，但体验随数据量劣化

**建议**：优先 trigram tokenizer（零依赖、SQLite 原生），如果索引体积不可接受再上 jieba。这是 P2，可延后。

---

## 三、目标架构：打开四道接缝

每道接缝 = 一个可替换点。实现替换不波及调用方。

```
┌─────────────────────────────────────────────────────────────┐
│  暴露层：CLI · REST API · Tauri Desktop（不变）              │
├─────────────────────────────────────────────────────────────┤
│  服务层：SyncService（统一）· search · replay                │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ 接缝①        │ 接缝②        │ 接缝③        │ 接缝④          │
│ Parser       │ Repository   │ SyncService  │ Settings       │
│ Protocol     │ Protocol     │ (已在上层)   │ (pydantic)     │
│ + Registry   │ Session/     │              │                │
│              │ Event/Search │              │                │
├──────────────┼──────────────┼──────────────┼────────────────┤
│ claude.py    │ SqliteStorage│ discover→    │ ~/.bagger/     │
│ cursor.py(待)│ PgStorage(待)│ parse→insert │ config.toml    │
│ codex.py(待) │ VectorStore  │ →export      │ + 环境变量      │
│              │ (为 memorized│              │                │
│              │  留口)       │              │                │
├──────────────┴──────────────┴──────────────┴────────────────┤
│  数据层：多源 JSONL · SQLite DB · (未来向量库)               │
└─────────────────────────────────────────────────────────────┘
```

**关键原则**：虚线（未来实现）和实线（当前实现）共享同一接口。接入第二个数据源 = 写一个新 Parser 类 + 注册，零改动调用方。

---

## 四、架构决策记录（ADR）

### ADR-001：引入 Parser Protocol + Registry

- **Status**：Proposed
- **Context**：`parser/` 只有 claude.py，scanner 硬编码 Claude 路径。设计意图（见 models 注释）是支持多源，但缺接缝。
- **Decision**：新增 `parser/base.py` 定义 `Parser` Protocol（`source_name: str`、`discover() -> list[Path]`、`parse(path) -> list[MemoryEvent]`、`parse_incremental(path, offset) -> list[MemoryEvent]`）。用 `ParserRegistry` 按 `source_name` 分发。`claude.py` 实现该 Protocol。
- **Consequences**：
  - 更容易：接入新数据源只写新 Parser + 注册
  - 更难：多一层间接，调试时要多跳一步
  - 可逆：Registry 是运行时注册，可随时移除

### ADR-002：引入 Repository Protocol

- **Status**：Proposed
- **Context**：services 依赖 `SqliteStorage` 具体类，无法 mock 测试，无法换存储后端。
- **Decision**：定义 `SessionRepository` / `EventRepository` / `SearchIndex` 三个 Protocol。`SqliteStorage` 实现全部（暂不拆文件）。services 类型注解改为 Protocol。
- **Consequences**：
  - 更容易：可 mock 测试；未来可换 Pg/Vector（为 memorized 向量检索留口）
  - 更难：Protocol 是结构化类型，IDE 跳转稍弱
  - 可逆：Protocol 不强制继承，随时可退回具体类

### ADR-003：抽取 SyncService 统一增量同步

- **Status**：Proposed
- **Context**：scanner 和 watcher 各有一份 discover→parse→insert→export 流水线，watcher 还 import scanner 的私有函数。
- **Decision**：新建 `services/sync.py` 的 `SyncService.sync_once(storage, parser, state)`。scanner 调一次，watcher 轮询调。`_parse_new_lines` 提升为 `Parser.parse_incremental` 公开方法。
- **Consequences**：
  - 更容易：修一处惠及两个入口；可加事件钩子
  - 更难：watcher 失去对轮询细节的直接控制（需 SyncService 暴露足够钩子）
  - 可逆：SyncService 只是抽取，逻辑等价

### ADR-004：集中 Settings

- **Status**：Proposed
- **Context**：DB_PATH 等配置散落 4 处，已出现重复定义。
- **Decision**：新建 `bagger/config.py`，用 `pydantic-settings` 的 `Settings`。字段：`db_path`、`claude_projects_dir`、`state_path`、`events_jsonl_path`、`api_host`、`api_port`。支持环境变量 `BAGGER_*` 覆盖。
- **Consequences**：
  - 更容易：单一真相源；用户可配置；环境变量覆盖
  - 更难：多一个 pydantic-settings 依赖（项目已用 pydantic，边际成本低）
  - 可逆：Settings 是数据类，可随时退回常量

### ADR-005：tool_uses 结构化表

- **Status**：Proposed
- **Context**：tool 统计用 SUBSTR/INSTR 从 `[tool_use:xxx]` 反解析，脆弱且慢。
- **Decision**：新增 `tool_uses` 表（id, event_id, tool_name, tool_id, tool_input_json）。parser 写 event 时同步插 tool_uses。统计改为 `GROUP BY tool_name`。写一次性迁移脚本回填历史数据。
- **Consequences**：
  - 更容易：结构化查询、可统计 tool_input、性能好
  - 更难：多一张表 + 迁移脚本
  - 可逆：旧 content_text 保留，统计可回退

### ADR-006：CJK 搜索改用 trigram tokenizer

- **Status**：Proposed（延后）
- **Context**：unicode61 不分词 CJK，回退 LIKE 全表扫描。
- **Decision**：FTS5 改用 `tokenize='trigram'`（SQLite 3.34+ 原生支持），中英文统一走 FTS5，消除 LIKE 分支。若索引体积不可接受，再评估 jieba。
- **Consequences**：
  - 更容易：中文有 ranking、统一代码路径
  - 更难：索引体积涨 3-5 倍；需 SQLite ≥ 3.34
  - 可逆：tokenize 是建表参数，可 rebuild

---

## 五、演进路线图

**原则**：每阶段独立可交付、可回滚、不中断现有功能。用适配器模式渐进迁移。

### 阶段 1 · 打开 P0 接缝（建议优先）

- [ ] ADR-004 Settings 集中（最简单，先做，为后续铺路）
- [ ] ADR-001 Parser Protocol + Registry，claude.py 适配
- [ ] ADR-002 Repository Protocol，SqliteStorage 适配
- [ ] 补 services 层测试（前置：Repository 接口让 mock 成为可能）

**验证标准**：现有 33 个测试全绿；CLI/API 行为零变化。

### 阶段 2 · 统一同步逻辑

- [ ] ADR-003 SyncService 抽取，scanner/watcher 改为调用方
- [ ] `_parse_new_lines` 提升为 `Parser.parse_incremental`

**验证标准**：scan/watch 行为等价；删除 watcher 对 scanner 私有函数的 import。

### 阶段 3 · 数据建模修正（按需）

- [ ] ADR-005 tool_uses 表 + 迁移脚本
- [ ] 统计查询改写

**验证标准**：stats 命令结果与迁移前一致。

### 阶段 4 · 搜索体验（按需，数据量上来再做）

- [ ] ADR-006 trigram tokenizer
- [ ] 评估索引体积，必要时上 jieba

**验证标准**：中文搜索有 BM25 ranking；LIKE 分支删除。

---

## 六、风险与回滚

| 风险 | 缓解 |
|------|------|
| Protocol 引入后 IDE 跳转变弱 | 用 `@runtime_checkable` + 类型注解；关键路径保留具体类注释 |
| SyncService 抽取遗漏 watcher 特有逻辑 | 先列出 watcher `_poll` 的所有副作用，逐条验证 SyncService 覆盖 |
| tool_uses 迁移脚本中断 | 迁移在事务内执行；保留 content_text 不删，统计可回退 |
| trigram 索引体积爆炸 | 先在副本库测试；体积超阈值则回退 LIKE + 上 jieba |

**回滚通用策略**：每道接缝都用适配器模式引入——新接口 + 旧实现包装。验证通过前不删旧路径。

---

## 七、与 memorized 的协同

用户同时在做的 **memorized**（AI Agent 智能长期记忆运行时，Zvec 向量存储 + SQLite + Kuzu 图谱）与 bagger 有天然协同：

- **ADR-002 的 Repository 接口** 为 memorized 的向量检索留口——未来 `VectorStore` 可以是 Repository 的另一个实现
- **bagger 的 MemoryEvent** 本身就是 memorized 的记忆原料
- **Parser Protocol** 让 memorized 能统一摄取多源 Agent 转录

建议：bagger 的存储接缝设计时，把 memorized 的向量检索需求纳入考量，但**不要现在实现**——接缝的存在比接缝的使用更有价值（reversibility）。

---

## 附录：评估依据

- 代码版本：bagger v0.1.0（pyproject.toml）
- 核心文件：`storage/sqlite.py`（528 行）、`services/scanner.py`、`services/watcher.py`、`parser/claude.py`、`models/event.py`、`api/dependencies.py`、`cli/main.py`
- 设计文档：`design/overview.md`（UI 设计，不含架构规划）
- 测试：`tests/` 3 个文件，覆盖 parser/storage/api，services 层无专门测试
