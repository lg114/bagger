# bagger · UI 设计系统

> 一套「设计系统先行」的界面方案，服务于 bagger 的核心场景：
> **快速搜索 → 浏览 → 回看 Claude Code 的历史对话记录**，把 AI 编码过程沉淀成可检索的「记忆」。

- **设计基调**：安静的编辑式 / 个人知识手帐（Quiet editorial）
- **主色逻辑**：温暖纸感底 + 墨色文字 + 单一陶土色点缀（避开 AI 俗套的青蓝渐变 / 霓虹）
- **密度**：低密度、发丝级边框、克制动效（照顾眩光敏感，不用纯黑纯白、不用满屏网格 / 旋转）
- **默认主题**：浅色；深色令牌已就位，可一键切换
- **可访问性**：WCAG AA（正文 ≥ 4.5:1）

---

## 🎨 设计基础

### 色彩系统（OKLCH，感知均匀）

| 角色 | Token | 说明 |
|------|-------|------|
| 纸面背景 | `--paper` `oklch(97% 0.008 75)` | 温暖近白，**非纯白**，降低眩光 |
| 卡片/抬升 | `--surface` `oklch(99% 0.005 75)` | |
| 浅井/侧栏 | `--surface-2` `oklch(94% 0.008 75)` | |
| 主文字 | `--ink` `oklch(26% 0.015 60)` | 温暖近黑，**非纯黑** |
| 次文字 | `--ink-soft` `oklch(45% 0.012 60)` | 纸面上 ≥ 4.5:1，可用于小字 |
| 装饰文字 | `--ink-faint` `oklch(60% 0.010 60)` | 仅大字号 / 装饰，不用于小字 |
| 发丝边框 | `--line` `oklch(90% 0.008 75)` | 低对比，安静 |
| 强调色 | `--accent` `oklch(60% 0.14 40)` 陶土 | 仅用于 CTA / 高亮 / 焦点，占比 ≈10% |
| 强调文字 | `--accent-strong` `oklch(52% 0.15 38)` | 纸面上作链接/文字，AA 安全 |
| 成功 | `--c-success` 松绿 `oklch(56% 0.09 155)` | 去饱和 |
| 警告 | `--c-warning` 赭黄 `oklch(72% 0.12 75)` | |
| 错误 | `--c-error` 砖红 `oklch(55% 0.15 28)` | |

**关键原则**
- 中性色全部带一丝暖调（chroma 0.008–0.012），不是死灰——自然且有凝聚力。
- 强调色稀有化：60-30-10 中仅占 10%，用在搜索框焦点环、主按钮、关键词高亮。
- 语义色去饱和，避免刺眼；错误/成功不靠颜色 alone，配合图标与文字标签。
- 深色模式**不是反色**：靠更亮的 surface 做层级，不靠阴影；文字降一点字重（`--on-accent` 等已调）。

### 字体系统

| 角色 | 字体 | 替代（fallback） | 用途 |
|------|------|------|------|
| 展示/标题 | **Fraunces** | Iowan Old Style, Georgia, serif | 品牌字、大标题，带编辑式温度 |
| 界面/正文 | **Hanken Grotesk** | system-ui, sans-serif | 全部 UI 与正文（非 Inter，更有性格） |
| 等宽/元信息 | **JetBrains Mono** | ui-monospace, monospace | 时间、项目名、代码、token |

- 字号：固定 rem 比例（应用 UI 用固定，可预测）：`12 / 13 / 16 / 20 / 28`，Hero 用 `clamp(2rem, 1.4rem+2vw, 3rem)`。
- 行高：正文 `1.6`（安静阅读），标题 `1.2`，元信息 `1.4`。
- 字重：`400 / 500 / 600`；展示标题用 600。
- 用 `font-variant-numeric: tabular-nums` 对齐数字；代码关闭连字。

### 间距系统（4pt 基准）

`4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 96 px`
命名按语义（`--space-sm`…），不按数值。兄弟间距用 `gap`，不靠 margin。

### 圆角 / 阴影 / 动效

- 圆角：温和不过分——`6 / 10 / 16px`，胶囊 `999px`。
- 阴影：极克制，默认靠发丝边框做层级；仅 hover 用 `--shadow-md`。
- 动效：`cubic-bezier(0.25,1,0.5,1)`（ease-out-quart），`160/260/380ms`；**无回弹/弹性**；尊重 `prefers-reduced-motion`。

---

## 🧱 组件库（映射核心场景）

### 基础组件
- **App Shell**：顶栏（品牌 + 全局搜索 + 同步状态）+ 左侧筛选栏 + 主区。浅色 sticky 顶栏带轻微毛玻璃。
- **搜索框（Hero）**：主场景第一入口，大、安静、单一焦点；聚焦时边框转强调色 + 焦点环。带 `⌘K` 提示。
- **结果列表（记忆项）**：**不套卡片**——用发丝分隔线 + 充裕留白做分组；每条 = 日期列 + 标题(Fraunces) + 元信息(等宽) + 摘要(关键词 `<mark>` 高亮) + 标签。
- **会话时间线（回看）**：纵向事件流。事件类型用「左侧色点 + 文字标签」双编码（用户/助手/工具/错误），不靠颜色 alone；工具调用显示为安静代码块。
- **按钮**：主(陶土填充) / 次(发丝边框) / 幽灵(纯文字)。主按钮稀有化。
- **标签 / 胶囊 / 状态 Pill**：低对比、安静。

### 组件状态
- **交互态**：默认 / hover / active / focus-visible（2px 强调色环，offset 2px）/ disabled。
- **空态**：有教育意义，引导换关键词或选项目，不堆砌信息。
- **加载/错误**：骨架屏 + 安静的提示，避免闪烁与强对比。

### 响应式
- ≤900px：侧栏转横向筛选行，主区单列。
- ≤560px：日期/标签栏折叠为单列；顶栏搜索隐藏（移入 Hero）。
- 用容器查询思路组织卡片，避免视口 hack。

---

## ♿ 可访问性

- **对比度**：正文/次文字在纸面上 ≥ 4.5:1；强调文字用 `--accent-strong` 保证 AA。
- **键盘**：全功能可 Tab 操作；`focus-visible` 清晰；逻辑 tab 顺序。
- **屏幕阅读器**：语义标签（`header/nav/main/article/section/search`），图标 `aria-hidden`，含 `.sr-only` 隐藏标签。
- **触控**：交互元素最小 40–44px 命中区。
- **动效敏感**：`prefers-reduced-motion` 下动效近乎关闭。
- **缩放**：字号用 rem，支持 200% 缩放不破版。
- **不靠颜色**：状态/类型均配图标 + 文字。

---

## 🔧 如何接入现有 React + Tailwind + Tauri 应用

设计令牌已写成框架无关的 `tokens.css` / `components.css`（见同目录）。两种接入方式：

**方式 A · 直接引入 CSS 变量（最快，零改 Tailwind 配置）**
```ts
// src/main.tsx 或全局入口
import './styles/tokens.css';
import './styles/components.css';
// 组件里用 var(--accent) 等
```

**方式 B · 映射到 Tailwind theme（推荐长期）**
```ts
// tailwind.config.ts
import { tokenToRgb } from './tokens'; // 把 oklch 预编译为 rgb 更稳
export default {
  theme: {
    extend: {
      colors: {
        paper: 'var(--paper)', surface: 'var(--surface)',
        ink: 'var(--ink)', accent: 'var(--accent)',
        // ...
      },
      fontFamily: {
        display: ['Fraunces', 'serif'],
        sans: ['Hanken Grotesk', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      spacing: { 1:'4px',2:'8px',3:'12px',4:'16px',5:'24px',6:'32px',8:'64px' },
    },
  },
};
```
> 注意：Tailwind 默认调色板与本系统冲突，建议在 `theme.extend` 中覆盖关键色，或直接以 CSS 变量为准，避免双来源。

**深色模式**：在 `<html data-theme="dark">` 切换即可，语义令牌自动重定向；Tauri 下可读取系统偏好或存用户选择。

**字体加载**：通过 Google Fonts 引入 Fraunces / Hanken Grotesk / JetBrains Mono；建议用 `font-display: swap` + 度量回退，减少 CLS。

---

## 📐 设计 QA 清单（交付前自检）

- [ ] 全站对比度 ≥ 4.5:1（用 WebAIM / DevTools 视觉缺陷模拟复核）
- [ ] 所有交互元素有 `focus-visible` 且 tab 可达
- [ ] 无满屏网格 / 旋转图案（眩光友好）
- [ ] 强调色占比 ≤ 10%，无 CTA 泛滥
- [ ] 响应式三档断点无破版
- [ ] 200% 缩放下可用
- [ ] 深浅主题切换后语义色仍可读

---

**UI Designer**：像素君
**设计系统日期**：2026-07-14
**状态**：可交付开发；预览见 `preview.html`（内含浅/深切换）
**后续**：组件库可按此令牌继续扩展（对话框 / 表格 / 设置页 / 同步管理）
