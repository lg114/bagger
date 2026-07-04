# Overview — 工程化地基 + README 更新

## 背景

团队需要资深开发者的代码质量把控。介入后发现 README 缺口本质是工程化基础设施缺失——
`pyproject.toml` 没有任何代码质量工具配置，没有贡献规范。按"先补地基，再让 README 如实
反映"的顺序推进。

## 完成项

### 1. ruff 配置（`pyproject.toml`）
- 规则集：`E` / `F` / `I` / `UP` / `B` / `SIM`
- `line-length = 100`，`target-version = "py312"`
- 排除 `ui` / `design` / `build` / `dist` / `.workbuddy`
- 加入 `dev` 依赖，同时补 `httpx`（FastAPI TestClient 依赖，原未声明）

### 2. 代码自动修复
- `ruff check --fix`：60 个安全违规自动修复
  - 25× `Optional[X]` → `X | None`
  - 5× 未用 import 清理
  - 5× import 排序
  - 5× `datetime.timezone.utc` → `datetime.UTC`
  - 4× 冗余 open modes
  - 其他 pyupgrade 项
- `ruff format`：11 个文件重新格式化
- 剩余 8 个不安全修复（SIM105/UP042/E741 等）留给团队 review

### 3. CONTRIBUTING.md（新建）
覆盖：开发环境、ruff 门禁、项目结构、分层规则、Conventional Commits、
PR 流程、Code Review 清单、新增 CLI/API 操作指引。

### 4. README.md 更新
- 顶部加 shields.io badges
- 新增 Tech stack 表
- 新增 Project structure 章节
- 扩充 Development（ruff 命令 + 提交前门禁）
- 新增 Contributing 章节（链接 CONTRIBUTING.md）
- 新增 Roadmap 占位

## 验证结果

- ✅ 33 个测试全过（`pytest tests/ -q`）
- ✅ 32 文件 format 合规
- ✅ ruff 修复未破坏任何功能

## 改动范围

17 文件修改 + 1 新建（CONTRIBUTING.md），+314/-190 行。

## 后续建议（按优先级）

1. **CI pipeline** — GitHub Actions 跑 `ruff check` + `pytest`，PR 必须绿才能合并
2. **Pre-commit hook** — 本地提交前自动跑 ruff，避免 CI 来回
3. **处理剩余 8 个不安全修复** — 特别是 UP042（StrEnum）需测试 pydantic 序列化
4. **ADR-001~006 落地** — 早上架构评估给出的四道接缝（Parser Protocol、Repository 等）
5. **可选：mypy** — bagger 已用 pydantic，配 mypy 能最大化类型安全收益（用户这次没选，后续可考虑）

## 关键文件

- `pyproject.toml` — ruff 配置 + dev 依赖
- `CONTRIBUTING.md` — 团队规范明文
- `README.md` — 对外门面
