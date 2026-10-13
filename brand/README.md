# Xu 品牌资产

两套主源，**不要混用**：

| 文件 | 用途 |
|------|------|
| [`xu_classic.svg`](xu_classic.svg) | **内容标识**：页面、文档、favicon、VS Code 扩展图标 |
| [`xu_app_logo.svg`](xu_app_logo.svg) | **桌面图标**：Dock、托盘、窗口、`.icns` / `.ico`、异形蒙版 |

PNG 由 SVG 导出（512×512）：`xu_classic.png`、`xu_app_logo.png`。  
`xu_app_icon.png` / `.svg` 是桌面 logo 的路径别名（旧代码仍认这个名字）。

仓库根目录有同内容短路径副本。**改图只改本目录 SVG**，再导出：

```bash
rsvg-convert -w 512 -h 512 brand/xu_classic.svg -o brand/xu_classic.png
rsvg-convert -w 512 -h 512 brand/xu_app_logo.svg -o brand/xu_app_logo.png
cp brand/xu_app_logo.png brand/xu_app_icon.png
cp brand/xu_app_logo.svg brand/xu_app_icon.svg
cp brand/xu_classic.svg brand/xu_classic.png brand/xu_app_logo.svg brand/xu_app_logo.png \
   brand/xu_app_icon.svg brand/xu_app_icon.png .
rsvg-convert -w 256 -h 256 brand/xu_classic.svg -o "${XU_VSCODE_ROOT:-../vscode}/images/icon.png"
```

桌面应用 `brand/` 约定：`xu_app_logo.png`（图标 / 蒙版；亦认 `icon.png`、`xu_app_icon.png`）+ `xu_classic.svg`（WebView 内容）。
