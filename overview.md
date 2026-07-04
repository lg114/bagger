# Overview — CI 落地 + 不安全修复清零

## 这一轮做了什么

在上一轮工程化地基（ruff 配置 + CONTRIBUTING + README）之上，补上质量门禁的最后一环：
**GitHub Actions CI**，并把上一轮遗留的 8 个不安全修复全部手动处理清零，确保第一次
push 就全绿。

## 完成项

### 1. CI pipeline（`.github/workflows/ci.yml`）
- 触发：push 到 main、PR 到 main
- 矩阵：Python 3.12 + 3.13（跨版本验证）
- 6 步：checkout → setup-python (带 pip cache) → install deps → ruff check → ruff format --check → pytest
- `"on":` 加引号（YAML 1.1 会把裸 `on` 解析成布尔 True，GitHub 自己能处理但其他工具会误判——工程严谨）

### 2. 8 个不安全修复全部手动处理

| 规则 | 文件 | 处理方式 |
|------|------|----------|
| E501 (1) | `api/app.py` | 描述字符串换行 |
| SIM115 (1) | `exporters/jsonl.py` | `# noqa: SIM115` 带理由（exporter 有意保持文件打开，with 会破坏 flush 语义） |
| UP042 (2) | `models/event.py` | `(str, Enum)` → `StrEnum`，跑测试验证 pydantic v2 序列化无碍 |
| E741 (1) | `services/replay.py` | 变量 `l` → `line` |
| SIM105 (3) | `scanner.py` / `watcher.py` / `sqlite.py` | try-except-pass → `contextlib.suppress` |

### 3. 文档同步
- README：加 CI badge，Roadmap 里 CI 项标 `[x]`
- CONTRIBUTING：新增 "CI — this runs on every push and PR" 章节，说明三道门禁和本地一致性

## 验证（完整 CI 模拟，本地跑了一遍 workflow 的全部步骤）

```
ruff check .            → All checks passed! (0 errors, 之前 8)
ruff format --check .   → 32 files already formatted
pytest tests/ -q        → 33 passed in 1.15s
YAML safe_load          → 语法验证通过
```

**CI verdict: ALL GREEN** —— push 上去第一次就会绿。

## 累计改动（两轮合计）

- 新建：`CONTRIBUTING.md` + `.github/workflows/ci.yml`
- 修改：`pyproject.toml` + `README.md` + 12 个 Python 源文件
- 代码质量：68 个 ruff 违规清零（60 自动 + 8 手动）

## 工程化闭环现在长这样

```
开发者写代码
    ↓
本地: ruff check + format + pytest  ← CONTRIBUTING.md 规定的提交前门禁
    ↓
push / 开 PR
    ↓
CI 自动跑同样的三道门禁 (Python 3.12 + 3.13)
    ↓
全绿 → 可合并    任意失败 → PR 红叉, 阻止合并
```

**规范从"贴在墙上"变成了"焊在流水线上"。**

## 下一步建议

1. **开启分支保护** — GitHub 仓库设置 → Branches → main → 勾选 "Require status checks to pass"，把 CI job 设为必须。这是 CI 门禁真正生效的最后一步（否则红叉也能合并）
2. **Pre-commit hook** — 本地 git hook，提交前自动跑 ruff，避免推上去才发现
3. **ADR-001~006 落地** — 架构评估给出的四道接缝（Parser Protocol、Repository 等）

## 关键文件

- `.github/workflows/ci.yml` — CI 配置
- `pyproject.toml` — ruff 配置 + dev 依赖
- `CONTRIBUTING.md` — 团队规范（含 CI 章节）
- `README.md` — 对外门面（含 CI badge）
