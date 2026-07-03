# bagger UI 设计方案 · 概览

## 交付物
- `design/bagger-ui-design.html` — 单文件高保真设计稿，浏览器直接打开预览，左侧导航切换 7 个视图（设计系统 + 6 个页面）。

## 设计定位
bagger 是面向开发者的本地优先工具（同步 Claude Code 转录到可搜索 SQLite + FTS5，Tauri 桌面端 1200×800）。界面遵循「克制、密度、可读」三原则：深色基底降低长时间浏览负担，靛紫主色仅用于可交互与状态强调，数值与代码用 Fira Code 等宽呈现以强化数据可信赖感。

## 信息架构（6 页面）
1. **Dashboard** — 4 个 KPI（会话/事件/Token/FTS 状态）+ 最近会话表 + 每日事件迷你柱图 + 高频工具 + 快捷操作
2. **Sessions** — 筛选栏（项目/时间/工具/排序）+ 会话表格（ID/路径/分支/模型/事件/Token/工具/时间）+ 分页
3. **Conversation** — 会话元信息头 + 回放控制 + 事件流（user/assistant/thinking/tool 四角色色）+ 右侧大纲与角色分布
4. **Search** — 大搜索框 + 语法提示 + 多维筛选 + 结果列表（snippet 高亮、来源、角色 badge）
5. **Analytics** — 每日事件柱图 + Token input/output 折线 + 工具使用排行 + 模型环形图 + 角色分布
6. **Settings** — 数据源 / 扫描同步 / 外观 / 数据维护 / 关于

## 设计系统
- **色彩**：bg `#0D0F17`/`#14171F`/`#1C2030`，border `#262A36`，主色 accent `#7C6CFF`，语义 teal/amber/red/blue，对话角色色 4 种
- **字体**：Fira Sans（UI）+ Fira Code（数据/代码），4 级字号 11/12/13/15/24
- **间距**：8pt 基准（4/8/12/16/20/24/32/64）
- **圆角**：6/8/12/16
- **组件**：按钮（primary/ghost/danger）、KPI 卡、表格、badge、tag、分段控件、开关、输入、图表（Chart.js）
- 全部以 CSS 变量暴露，便于 Tailwind `@theme` 映射与深浅主题切换

## 关键决策
- Conversation 单列事件流 + 右侧大纲，而非双栏对话——因为含 thinking/tool call 等非对话事件，纵向流更清晰
- Search 结果按角色着色 badge，snippet 用 `<mark>` 高亮，符合 FTS5 返回结构
- Analytics 用 Chart.js 真实渲染（柱/折线/环形），非占位图
- 全局能力：扫描状态指示器（顶栏）、数据库健康徽标（侧栏底）、⌘K 快捷搜索

## 后续
- 可将 CSS 变量直接映射到项目 `ui/` 的 Tailwind 配置
- 各页面 mockup 可作为 React 组件拆分依据
