# Xu Flow

用 `#ui/webview` 把 `xu map --graph` 画成 HTML SVG。左侧是**函数树**：每个函数下面挂它的控制流节点和源码注释（自动换行）；右侧图与树对应高亮。函数之间的调用是紫色折线。

这是桌面应用（标准库 `#ui` / `#ui/webview`），不是语言核心，也不是 bootstrap。

默认打开自带样例 `developer/xu_flow/sample`（多函数互相调用的票价计算）。

## 运行

仓库根：

```bash
make xu-map xu-desktop

xu-desktop pack developer/xu_flow --target macos-arm64 --webview -o /tmp/XuFlow
# pack 后把 xu-map 和 sample 放进 .app（不要对 xu-map 再 codesign --deep）：
cp bin/xu-map /tmp/XuFlow.app/Contents/MacOS/xu-map
mkdir -p /tmp/XuFlow.app/Contents/MacOS/sample
cp developer/xu_flow/sample/main.xu /tmp/XuFlow.app/Contents/MacOS/sample/
open /tmp/XuFlow.app
```

也可：

```bash
xu build developer/xu_flow --target macos-arm64 --desktop --webview -o /tmp/XuFlow
```

指定源路径：

```bash
open /tmp/XuFlow.app --args ../xu-examples/examples/03_control_flow
```

## 操作

- 拖动画布平移，滚轮缩放（⌘/Ctrl+滚轮更明显）
- 左侧函数树：点函数名展开，节点挂在树下，注释在树里换行；点树节点会在图里对上并居中
- 点图里的函数卡片展开（可同时开多个）；再点标题收回。顶部 **全开** / **全收**
- 点节点或绑定名填值；**simulate** 按当前值走 `if` / `match` / 循环边并高亮路径
- 落在路径上的调用箭头会跟着亮起来

`xu-map --graph` 输出节点/边表（`N` / `E` 行，含 `call` 边）。默认 `xu map` 仍是 Mermaid。
