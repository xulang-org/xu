# Xu 品牌资产

两套主源，**不要混用**：

| 文件 | 用途 |
|------|------|
| [`xu_classic.svg`](xu_classic.svg) | **内容标识**：页面、文档、favicon、VS Code 扩展图标 |
| [`xu_app_logo.svg`](xu_app_logo.svg) | **桌面图标**：Dock、托盘、窗口、`.icns` / `.ico`、异形蒙版 |

PNG 由 SVG 导出（512×512）：`xu_classic.png`、`xu_app_logo.png`。  
`xu_app_icon.png` / `.svg` 是桌面 logo 的路径别名（旧代码仍认这个名字）。

品牌文件以本目录为准；仓库根目录没有短路径副本。**改图只改本目录 SVG**，安装 `rsvg-convert`（librsvg）后，从仓库根目录导出 PNG 并更新本目录的旧路径别名：

```bash
rsvg-convert -w 512 -h 512 brand/xu_classic.svg -o brand/xu_classic.png
rsvg-convert -w 512 -h 512 brand/xu_app_logo.svg -o brand/xu_app_logo.png
cp brand/xu_app_logo.png brand/xu_app_icon.png
cp brand/xu_app_logo.svg brand/xu_app_icon.svg
```

如需更新扩展图标，以下命令会写入扩展仓库（默认同级 `../vscode-xu`）；其他布局先设置 `XU_VSCODE_ROOT`：

```bash
rsvg-convert -w 256 -h 256 brand/xu_classic.svg -o "${XU_VSCODE_ROOT:-../vscode-xu}/images/icon.png"
```

[`xu_cli_banner.txt`](xu_cli_banner.txt) 是品牌展示样稿，不代表当前编译器版本或宿主目标。图标字体展示见 [`fonts/xu-icons/demo.html`](fonts/xu-icons/demo.html)，设计规范见 [`VI_MANUAL.md`](VI_MANUAL.md)。

桌面应用 `brand/` 约定：`xu_app_logo.png`（图标 / 蒙版；亦认 `icon.png`、`xu_app_icon.png`）+ `xu_classic.svg`（WebView 内容）。
