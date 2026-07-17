# bagger · UI 设计系统

> 一套「设计系统先行」的界面方案，服务于 bagger 的核心场景：
> **快速搜索 → 浏览 → 回看 Claude Code 的历史对话记录**，把 AI 编码过程沉淀成可检索的「记忆」。

- **设计基调**：安静的编辑式 · 暗色版（Quiet editorial · dark only）
- **主色逻辑**：暖近黑底 + 暖白字 + 单一陶土色点缀（替换初版的 Teal + Violet 霓虹）
- **密度**：低密度、发丝级边框、克制动效（照顾眩光敏感，不用纯黑纯白、不用满屏网格 / 旋转）
- **主题**：**仅暗色**（light mode 已彻底移除）
- **可访问性**：WCAG AA（正文 ≥ 4.5:1 对比度，正文色 `oklch(92% …)` 对底 `oklch(16% …)` 远超此线）

---

## 真源说明（重要）

设计令牌的**唯一真源是 `ui/src/index.css`**（Tailwind v4 `@theme` + `:root` CSS 变量），不是本目录下的 `tokens.css` / `components.css`。

`design-system/` 下的 `tokens.css` / `components.css` / `preview.html` 是 **2026-07-14 的初版浅色原型**，仅作历史参考；真源于 2026-07-15 起演进为暗色陶土体系并落在 `ui/src/index.css`。**不要**以这些旧文件为准。

---

## 设计基础

### 色彩系统（OKLCH，感知均匀，暗色）

所有中性色带一丝暖调（chroma 0.006–0.010，hue ≈ 65–75），不是死灰——自然且有凝聚力。

#### 背景 Backgrounds — 暖近黑（never pure #000，glare-friendly）

| Token | 值 | 用途 |
|-------|-----|------|
| `--bg-base` | `oklch(16% 0.006 65)` | 应用根底、主内容区 |
| `--bg-surface` | `oklch(19% 0.007 65)` | 卡片 / 抬升面 / 容器底 |
| `--bg-elevated` | `oklch(23% 0.008 65)` | 次级抬升（下拉、次级信息块） |
| `--bg-code` | `oklch(15% 0.006 65)` | 代码块底（比 base 更暗，做凹进） |
| `--bg-input` | `oklch(17% 0.007 65)` | 输入框底 |

#### 文字 Text — 暖白（never pure #fff）

| Token | 值 | 用途 |
|-------|-----|------|
| `--text-primary` | `oklch(92% 0.008 75)` | 主文字、标题 |
| `--text-secondary` | `oklch(75% 0.010 70)` | 次级文字、标签 |
| `--text-tertiary` | `oklch(60% 0.010 70)` | 元信息、装饰、时间戳 |
| `--text-muted` | `oklch(60% 0.010 70)` | = `--text-tertiary` 的语义别名 |
| `--text-placeholder` | `oklch(52% 0.010 70)` | 输入占位 |

#### 边框 Borders — 暖发丝，低对比（calm）

| Token | 值 | 用途 |
|-------|-----|------|
| `--border-subtle` | `oklch(27% 0.008 65)` | 列表行 / 容器内发丝线（用得最多） |
| `--border-medium` | `oklch(30% 0.008 65)` | 卡片边框（`glass-card` / `glass-card-static`） |
| `--border-strong` | `oklch(24% 0.008 65)` | 输入框边框 |

#### 强调 Accent — 陶土 / 赤陶（clay / terracotta，单一品牌色）

| Token | 值 | 用途 |
|-------|-----|------|
| `--brand-400` | `oklch(74% 0.12 44)` | 链接 / 浅强调文字 |
| `--brand-500` | `oklch(64% 0.13 42)` | **主强调**——CTA、hover 竖条、焦点环、图标激活 |
| `--brand-600` | `oklch(56% 0.14 40)` | 主按钮按压态 |
| `--brand-bg` | `oklch(64% 0.13 42 / 0.14)` | 陶土底色（hover 行底、code chip 底） |

> 另有一组 `--accent-*`（`--accent-300/500/600`、`--accent-bg`、`--accent-foreground`）与 `--brand-*` **同值**，供 shadcn 风格的 `button.tsx` 等组件复用（`--color-accent` 映射到 `--accent-500`）。两者等价，新代码统一用 `--brand-*` 即可。

#### 语义色 Semantic

| Token | 值 | 用途 |
|-------|-----|------|
| `--success` | `oklch(74% 0.13 155)` | 松绿（去饱和），工具结果、新事件 |
| `--success-subtle` | `oklch(34% 0.07 155)` | 成功底色 |
| `--warning` | `oklch(80% 0.12 82)` | 赭黄，注意 / 警告 |
| `--warning-subtle` | `oklch(38% 0.08 78)` | 警告底色 |
| `--error` | `oklch(70% 0.15 25)` | 砖红，错误 |
| `--error-subtle` | `oklch(36% 0.10 25)` | 错误底色 |
| `--info` | `oklch(72% 0.10 225)` | 静蓝，信息 |
| `--rose-400/500` | `oklch(72% 0.13 25)` / `oklch(64% 0.15 22)` | 玫红，仅用于「未读 / 新增」等稀有点缀 |

#### 交互与层级 Interaction

| Token | 值 | 用途 |
|-------|-----|------|
| `--focus-ring` | `oklch(64% 0.13 42)` | `:focus-visible` 焦点环（= `--brand-500`） |
| `--nav-active-bg` | `oklch(64% 0.13 42 / 0.12)` | 侧栏导航激活底 |
| `--nav-active-text` | `oklch(78% 0.11 46)` | 侧栏导航激活文字 |
| `--nav-active-border` | `oklch(64% 0.13 42 / 0.30)` | 侧栏导航激活左竖条 |
| `--card-hover-shadow` | `0 10px 32px -12px …brand…, 0 4px 14px -6px …black…` | 卡片 hover 抬升阴影（极克制） |

#### 图着色 Graph（会话关系图，warm editorial）

`--node-session`(陶土) / `--node-file`(暖沙) / `--node-topic`(梅紫) / `--node-model-opus`(松绿) / `--node-model-sonnet`(静蓝)；
`--edge-session-file` / `--edge-session-project` / `--edge-session-topic` / `--edge-session-session`（均为带透明度的同色系）。

**关键原则**
- 强调色稀有化：60-30-10 中陶土仅占 ≈10%，用在搜索焦点、主按钮、关键词高亮、导航激活。
- 语义色去饱和，不靠颜色 alone —— 错误/成功/类型均配合图标 + 文字标签。
- 暗色**不是反色**：靠更亮的 surface 做层级，不靠阴影；默认层级靠发丝边框，仅 hover 用 `--card-hover-shadow`。
- **透明度修饰符对 oklch 变量不生效**：需要半透明一律用 `color-mix(in oklch, var(--brand-500) 15%, transparent)` 或显式 `/ 0.14` alpha 槽（如 `--brand-bg`），不要写 `bg-primary/15` 这类 Tailwind 语法——它不产生 alpha。

### 字体系统

| 角色 | 字体 | 替代（fallback） | 用途 |
|------|------|------|------|
| 展示 / 标题 | **Fraunces** | Iowan Old Style, Georgia, serif | 页头大标题、区块标题（`font-display`），带编辑式温度 |
| 界面 / 正文 | **Hanken Grotesk** | system-ui, sans-serif | 全部 UI 与正文（`font-sans`） |
| 等宽 / 元信息 | **JetBrains Mono** | ui-monospace, monospace | 时间、项目路径、代码、token（`font-mono`） |

- 字号：标题 `text-2xl`(24) / `text-3xl`(30，页头) / 区块 `font-display`；正文 14–16；元信息 11–13。
- 行高：正文 `1.6`（markdown）、标题 `1.2`、元信息 `1.4`。
- 字重：`400 / 500 / 600`；展示标题用 600。
- 数字一律 `tabular-nums`（`font-variant-numeric`）对齐；代码关连字。
- 字体经 `ui/index.html` 由 Google Fonts 引入（**打包前建议改自托管 woff2**，避免运行时外链）。

### 间距系统（4pt 基准）

`4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 px`。语义化优先，兄弟间距用 `gap` 不靠 margin。
主内容区 padding 响应式：`px-5 py-6`（窄）→ `md:px-8` → `lg:px-10 lg:py-10` → `xl:px-12 xl:py-10`。

### 圆角 / 阴影 / 动效

- 圆角：`--radius-card` **12px**（列表容器、卡片、弹窗）、`--radius-element` **8px**（按钮、输入、小卡）；胶囊 `999px`。
- 阴影：极克制，默认靠发丝边框做层级；仅 `hover` 用 `--card-hover-shadow`。
- 动效（ease-apple = `cubic-bezier(0.4, 0, 0.2, 1)`）：
  - `--animate-fade-in-up`：`fade-in-up 0.4s`（页面/区块入场）
  - `--animate-count-up`：`count-up 0.3s`（KPI 数字）
  - `--animate-pulse-glow`：`pulse-glow 3s`（搜索框聚焦，**低频**，眩光友好）
  - **无回弹 / 弹性**；全局尊重 `prefers-reduced-motion`（见下）；触摸设备 `hover: none` 时以 `:active` 替代 hover。

---

## 组件库（映射核心场景，当前实现）

### App Shell（Layout.tsx）
- **侧边栏 Memory Spine**：`bagger` 标题 + 折叠按钮 + `Browse`(Dashboard / Search / Projects) 与 `Manage`(Analytics / Scan / Settings) 两组导航；激活项左陶土竖条 + 陶土文字（`--nav-active-*`），无搜索框、无 logo 字标、无 Synced 绿点。
- 折叠态：纯图标脊（`w-14`），图标按钮保留 Search 等入口。
- **分区靠边框**：侧栏右边框 + 状态栏上边框做区域划分；主内容区**无顶部发丝线**（避免视觉切割）。
- 主区 `<main className="flex-1 overflow-y-auto min-w-0">`，内容 wrapper 响应式 padding（见上）。

### 列表统一语言（全站零分叉）
四类列表（Dashboard Recent / Conversations `SessionRow` / Search Results / Projects 组）均为同一套：

```
<容器 rounded-card overflow-hidden border border-[var(--border-subtle)]>
  <行 border-b border-[var(--border-subtle)] last:border-0
      hover:bg-[var(--brand-bg)] + 陶土左竖条(before)>
```

- 行间发丝线真实渲染（Border 放在 `<Link>`/`<li>` 直接子元素上，`last:border-0` 才命中）。
- 会话/搜索行：标题 + 项目路径(mono) + 消息数 + 日期，左→右布局。
- 搜索结果行额外带：角色标签（陶土/中性双调）+ FTS5 `<mark>` 高亮（`color-mix` 陶土底）。

### 会话时间线（SessionDetailPage + MessageBubble）
- 纵向事件流；事件类型用「**左侧色点 + 文字标签**」双编码，不靠颜色 alone：
  - You = 陶土 / Assistant = 松绿 / Tool = 梅紫 / Error = 红 / System = 灰
- 内容卡：`bg-[var(--bg-surface)] border border-[var(--border-subtle)]`（与发丝列表同语言）。
- `ContentBlock`：Thinking / Tool use / Tool result 为可折叠块；展开容器同样用 `bg-[var(--bg-surface)] + border-[var(--border-subtle)]`。

### 共享组件（已抽，单点维护，`ui/src/components/`）
| 组件 | 签名要点 | 用途 |
|------|----------|------|
| `MetricCard` | `{ label, value, icon, color, isLoading? }` | KPI 卡：色点 + 衬线大数字 + 安静图标；数字自动千分位 |
| `ErrorBlock` | `{ message, detail?, className? }` | 错误态：图标 + 文案（+ 可选 detail） |
| `SessionRow` (+ `SessionRowSkeleton`) | `{ session }` | 会话发丝行；骨架同构 |
| `EmptyState` | `{ icon?, title, description?: ReactNode, action?: {label,to} }` | 空态：图标 + 标题 + 描述 + 可选 CTA |

### 按钮（ui/components/ui/button.tsx）
- `primary`（陶土填充，稀有化）/ `secondary`（发丝边框）/ `ghost`（纯文字）。
- 主按钮 `:focus-visible` 用 `--focus-ring`；`disabled` 降透明度 + 禁指针。

### 其它基础组件
- **搜索框**：Hero 第一入口，聚焦时陶土焦点环 + `pulse-glow`（低频）。
- **角色 / 状态 Pill**：低对比、安静；语义色仅作点缀。
- **分页**：Conversations 页底部发丝分页条；后端按 `project` 过滤后 `meta.total` 即项目级计数。

### 组件状态
- **交互态**：默认 / hover / active / `:focus-visible`（2px 陶土环，offset 2px）/ disabled。
- **空态**：教育意义，引导换关键词或 `bagger scan`，不堆砌信息。
- **加载 / 错误**：骨架屏 + 安静提示（`Skeleton` 用 `bg-[var(--bg-elevated)]/60`），避免闪烁与强对比。

### 响应式
- 侧栏展开 240px；窄内容区（`<lg`）时，SessionDetailPage 的 metadata 面板**堆叠到主内容上方**（主区获完整宽度），而非挤压。
- 列表 / KPI 卡用 `grid-cols-1 → sm/md/lg` 渐进多列。
- 全程 `min-w-0` 链确保 markdown / 代码块 / 工具结果在 flex 收缩时正确换行或横向滚动，不撑出视口。
- 尊重 `prefers-reduced-motion`：所有入场/脉冲动效在开启时近乎关闭。

---

## 可访问性

- **对比度**：正文 `oklch(92%)` 对底 `oklch(16%)` 远超 4.5:1；强调文字用 `--brand-400` 保证 AA。
- **键盘**：全功能可 Tab；`focus-visible` 清晰（陶土环）；逻辑 tab 顺序；`<main>` 为内容区。
- **屏幕阅读器**：语义标签（`header/nav/main/article/section/search`）；图标 `aria-hidden`；必要处 `.sr-only` 隐藏标签。
- **触控**：交互元素最小 40–44px 命中区。
- **动效敏感**：`prefers-reduced-motion` 下动效近乎关闭；`hover: none` 设备以 `:active` 替代 hover。
- **缩放**：字号用 rem，支持 200% 缩放不破版。
- **不靠颜色**：状态 / 类型均配图标 + 文字。

---

## 如何接入（React + Tailwind v4 + Tauri）

**真源即 `ui/src/index.css`**，它已用 Tailwind v4 的 `@theme` 把 CSS 变量映射成 `bg-background` / `text-foreground` / `border-border` / `text-primary` / `bg-card` 等工具类。组件里直接写：

```tsx
// 用 Tailwind 工具类（来自 @theme 映射）
<div className="rounded-card border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
  <p className="text-primary">标题</p>
  <span className="text-muted-foreground font-mono">元信息</span>
</div>

// 或直接用 CSS 变量（最稳，避免 oklch 透明度陷阱）
<span style={{ background: 'color-mix(in oklch, var(--brand-500) 15%, transparent)' }} />
```

要点：
- **透明度**：对 `--brand-500` 这类 oklch 变量，**不要**写 `bg-primary/15`（Tailwind 的 `/N` 对 oklch 变量不产生 alpha）。改用 `bg-[var(--brand-bg)]` 或内联 `color-mix`。
- **字体**：`font-display` / `font-sans` / `font-mono` 已在 `@theme` 注册。
- **圆角**：`rounded-card`(12px) / `rounded-element`(8px)。
- **动效**：`animate-fade-in-up` / `animate-count-up`，统一走 `--ease-apple`。
- **light mode 已移除**：不要写 `data-theme="light"` 分支，全站仅暗色。

---

## 设计 QA 清单（交付前自检）

- [ ] 全站对比度 ≥ 4.5:1（DevTools 视觉缺陷模拟复核）
- [ ] 所有交互元素有 `:focus-visible` 且 tab 可达
- [ ] 无满屏网格 / 旋转图案（glare-friendly）
- [ ] 陶土强调占比 ≤ 10%，无 CTA 泛滥
- [ ] 列表四类视觉语言一致（圆角发丝容器 + 行间 border-b + 陶土 hover）
- [ ] 响应式：侧栏展开 + 窄屏下 SessionDetail 不横向溢出
- [ ] 200% 缩放下可用
- [ ] `prefers-reduced-motion` 下动效关闭

---

## 已知待清理（接手人注意）

> 以下为真源 `ui/src/index.css` 中**尚未收敛**的不一致，属技术债，不在本次文档同步范围：

- `.markdown-content code` / `blockquote` / `pre .copy-btn` 仍硬编码旧 **teal** `rgba(45, 212, 191, …)`，与陶土体系冲突。应改为 `var(--brand-bg)` / `var(--brand-400)` / `var(--border-subtle)` 等陶土真源（参考 `SearchResults` 的 `<mark>` 改法）。
- `design-system/tokens.css` / `components.css` / `preview.html` 为初版浅色原型，已弃用，可保留作历史参考但**不要**作为真源。

---

**UI Designer**：像素君
**设计系统日期**：2026-07-17（重写以对齐 `ui/src/index.css` 真源）
**状态**：可交付开发；真源 = `ui/src/index.css`
**后续**：清理上列「已知待清理」项；组件库可按此令牌继续扩展（对话框 / 表格 / 设置页深化）
