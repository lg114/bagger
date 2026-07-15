# bagger 设计系统 · 交付目录

为 bagger 桌面端建立的「设计系统先行」界面方案，深色编辑式、克制、低密度（眩光友好，dark-only），主场景是**搜索 / 浏览 / 回看 Claude Code 历史对话**。

## 文件

| 文件 | 内容 |
|------|------|
| `tokens.css` | 设计令牌：暖近黑/陶土配色（OKLCH，深色优先）、字体、4pt 间距、圆角、阴影、动效、浅色变体参考 |
| `components.css` | 核心组件：App Shell、搜索 Hero、结果列表、会话时间线、按钮、标签、空态、响应式、reduced-motion |
| `preview.html` | 自包含预览页：检索页 + 回看页，含**浅/深主题切换**（验证令牌真的可用） |
| `DESIGN_SYSTEM.md` | 完整设计规范 + 可访问性 + 如何接入 React+Tailwind+Tauri |

## 如何查看

直接用浏览器打开 `preview.html` 即可（无需起服务）。右上角「◐ 主题」可在浅/深之间切换，顶部「检索 / 回看」可切换两个核心视图。

## 设计基调

安静的编辑式 / 个人知识手帐——暖近黑底 + 暖白字 + 单一陶土色点缀。避开 AI 俗套的青蓝渐变与霓虹，低密度、发丝级边框、克制动效。

## 接入应用

见 `DESIGN_SYSTEM.md` 末尾「如何接入现有 React + Tailwind + Tauri 应用」（直接引 CSS 变量，或映射到 Tailwind theme）。
