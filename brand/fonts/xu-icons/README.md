# XuIcons · XU 官方字体图标库与纯矢量图元规范 (v2.0.0)

> **XuIcons** 是专为 XU 编程语言生态系统打造的高性能、纯矢量、全格式字体与图元库。全域覆盖 **370 款** 针对编译架构、语言语法、开发者工具、版本控制、分布式网络、数据存储、加密安全与原生 GUI 的核心图元。

---

## 📦 格式资产一览 (Asset Matrix)

| 资产文件 | 格式类型 | 尺寸 | 特性与适用场景 |
| :--- | :--- | :--- | :--- |
| **`xu-icons.woff2`** | WOFF2 字体 | **22.4 KB** | 极速网络传输，Brotli 高压缩率，现代浏览器首选格式 |
| **`xu-icons.woff`** | WOFF 字体 | 30.4 KB | 标准 Web 字体兼容回退格式 |
| **`xu-icons.ttf`** | TrueType 字体 | 75.4 KB | 操作系统本地安装、桌面 IDE、设计软件（Figma / Sketch） |
| **`xu-icons.svg`** | SVG Font | 185.6 KB | 矢量字体格式规范 |
| **`xu-icons.css`** | 样式表 | 47.9 KB | 内置 WOFF2 Base64 极速内嵌，零网络往返耗时；提供尺寸、旋转、动画等完整工具类 |
| **`xu-icons.defs.svg`** | SVG Symbol Sprite | 219.1 KB | 现代 SVG 雪碧图，370 款 `<symbol>`，支持 `<use>` 零抖动加载与 `currentColor` 换色 |
| **`svg/`** | 独立 SVG 目录 | 372 个文件 | 每一个图元均独立封装为标准 1000×1000 矢量 SVG 文件，可用于 Vite/Webpack 组件导入 |
| **`xu-icons.json`** | 规范元数据字典 | 314.1 KB | 完整 JSON 结构，包含中英文标签、分类、检索关键词、编码映射与 SVG 路径 `d` 数据 |
| **`demo.html`** | 交互式工作台展厅 | 313.4 KB | 中英双语切换、实时关键字检索、调色盘、多尺寸阶梯缩放、一键导出与单文件下载 |

---

## 🚀 快速上手 (Quick Start)

### 1. WebFont 方式 (推荐 Web 页面快速引入)

在 HTML `<head>` 中引入样式文件：

```html
<link rel="stylesheet" href="/fonts/xu-icons.css">
```

在页面任意位置渲染图标：

```html
<!-- 基础语法 -->
<i class="xi xi-logo"></i>
<i class="xi xi-terminal"></i>
<i class="xi xi-bolt"></i>

<!-- 尺寸微调工具类 -->
<i class="xi xi-code xi-xs"></i>  <!-- 0.75x -->
<i class="xi xi-code xi-sm"></i>  <!-- 0.875x -->
<i class="xi xi-code xi-lg"></i>  <!-- 1.333x -->
<i class="xi xi-code xi-2x"></i>  <!-- 2x -->
<i class="xi xi-code xi-fw"></i>  <!-- 等宽居中 (Fixed Width) -->

<!-- 动画与旋转工具类 -->
<i class="xi xi-loader xi-spin"></i>       <!-- 360° 无限平滑旋转 -->
<i class="xi xi-loader xi-pulse"></i>      <!-- 8 步脉冲式旋转 -->
<i class="xi xi-chevron-right xi-rotate-90"></i> <!-- 旋转 90 度 -->
<i class="xi xi-arrow-right xi-flip-h"></i>      <!-- 水平镜像翻转 -->
```

---

### 2. 现代 SVG Symbol Sprite 方式 (推荐现代化前端应用)

SVG `<use>` 方式具备零字体加载抖动 (FOIT/FOUT)、高精度亚像素抗锯齿、以及 CSS `currentColor` 自动着色能力：

```html
<!-- 引入全局雪碧图中的 Symbol 图元 -->
<svg class="xi xi-logo">
  <use href="/fonts/xu-icons.defs.svg#xi-logo"></use>
</svg>

<svg class="xi xi-terminal">
  <use href="/fonts/xu-icons.defs.svg#xi-terminal"></use>
</svg>
```

配套 CSS 基础样式规则：

```css
svg.xi {
  width: 1em;
  height: 1em;
  fill: currentColor;
  vertical-align: -0.125em;
  display: inline-block;
}
```

---

### 3. 单个独立 SVG 矢量组件 (React / Vue / Vite)

全套 370 款图标可在 `fonts/svg/` 目录中找到对应的单文件：

```tsx
// React (Vite SVG 插件示例)
import LogoIcon from '/fonts/svg/logo.svg?react';
import TerminalIcon from '/fonts/svg/terminal.svg?react';

export function Header() {
  return (
    <nav className="flex items-center gap-3">
      <LogoIcon className="w-6 h-6 text-rose-600" />
      <span className="font-bold">XU Language</span>
      <TerminalIcon className="w-5 h-5 text-slate-400" />
    </nav>
  );
}
```

---

### 4. XU 原生图形界面 (XUUI) 集成

XU 跨平台原生 GUI 引擎深度集成了 XuIcons 图元常量：

```xu
use xuui::prelude::*;
use xuui::icons as xi;

fn build_ui() -> View {
    VStack::new()
        .gap(12.px())
        .child(Button::new("运行构建").icon(xi::play).primary())
        .child(Button::new("版本提交").icon(xi::git_commit))
        .child(Icon::new(xi::logo).size(48.px()).color(Color::Brand))
}
```

---

## 🗂️ 11 大核心分类与图元分布

| 分类 (Category) | 图元数 | 领域与核心图元示例 |
| :--- | :---: | :--- |
| **Brand (品牌图腾)** | 15 | `logo`, `logo-wordmark`, `seal`, `xuflow`, `xupkg`, `xudocs`, `xuui`, `xuaot`, `xuvm` |
| **Language (语法与语义)** | 34 | `ownership`, `borrow`, `borrow-mut` ($&T), `affine`, `move`, `coroutine`, `channel`, `mutable` ($) |
| **Compiler (编译器与运行时)** | 16 | `terminal`, `cpu`, `memory`, `mir`, `ast`, `token`, `binary`, `asm`, `gc-free`, `thread` |
| **DevTools (开发者工具)** | 37 | `code`, `terminal-box`, `curly-braces`, `brackets`, `breakpoint`, `callstack`, `flamegraph` |
| **Git & DevOps (版本与运维)** | 24 | `git-branch`, `git-commit`, `git-merge`, `git-pull-request`, `pipeline`, `container`, `rocket` |
| **Network (网络与协议)** | 28 | `globe`, `server`, `cloud`, `wifi`, `bluetooth`, `router`, `http`, `socket`, `websocket` |
| **Database & Storage (数据库)** | 14 | `database`, `database-table`, `database-query`, `database-lock`, `hard-drive`, `ssd`, `archive` |
| **Security & Auth (安全鉴权)** | 17 | `security`, `lock`, `unlock`, `key`, `shield-check`, `fingerprint`, `certificate`, `vpn` |
| **Files & Media (文件与媒体)** | 38 | `file`, `file-code`, `file-binary`, `file-pdf`, `folder-tree`, `image`, `video`, `equalizer` |
| **Hardware & Devices (设备硬件)** | 21 | `monitor`, `laptop`, `smartphone`, `chip`, `gpu`, `motherboard`, `keyboard`, `sensor` |
| **UI & Math (界面与数学运算)** | 126 | `sun`, `moon`, `palette`, `search`, `bell`, `plus`, `minus`, `infinity`, `pi`, `sigma`, `atom`, `dna` |

---

## 🛠️ 元数据标准 (`xu-icons.json`)

`xu-icons.json` 提供结构化的图元设计规范契约：

```json
{
  "name": "channel",
  "code": "0xe91d",
  "unicode": "\\e91d",
  "category": "Language",
  "categoryEn": "Syntax & Semantics",
  "label": "类型化无锁通道 chan",
  "labelEn": "Typed Lock-Free Channel chan",
  "keywords": ["language", "channel", "queue", "lockfree", "通道", "并发"],
  "aliases": ["crypto"],
  "svg": "M 200 300 L 800 300 ... Z"
}
```

---

## 🎨 展厅预览 (Showroom)

本地打开 `demo.html` 或在运行的官网中访问 `/fonts/demo.html`，即可体验：
- **实时双语切换**：中英文标签与界面语言即时生效。
- **高阶检索过滤**：支持通过图标名称、中文释义、英文释义、拼音关键字、分类以及十六进制编码实时过滤。
- **图标详情抽屉**：预览 16px、24px、32px、48px、64px、128px 多尺寸阶梯渲染效果。
- **一键格式导出**：提供 WebFont HTML 标签、SVG Sprite 引用、CSS 类名、Unicode 字符实体及原始 SVG 代码复制。
- **单图标文件下载**：点击详情弹窗中的“下载独立 SVG”即可导出对应的标准矢量文件。
