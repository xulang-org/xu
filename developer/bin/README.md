# 预编译产品编译器

本目录存放各托管平台的 **产品 `xu` 编译器**，命名：

```text
xu.<os>.<arch>
```

由 `--target <os>-<arch>` 交叉编译后改名而来（点号分隔，与 CLI 目标名一一对应）。

| 文件 | `--target` | 格式 |
|------|------------|------|
| `xu.macos.arm64` | `macos-arm64` | Mach-O arm64 |
| `xu.macos.x64` | `macos-x64` | Mach-O x86_64 |
| `xu.linux.arm64` | `linux-arm64` | ELF aarch64 |
| `xu.linux.x64` | `linux-x64` | ELF x86_64 |
| `xu.linux.loongarch64` | `linux-loongarch64` | ELF LoongArch |
| `xu.linux.riscv64` | `linux-riscv64` | ELF RISC-V |
| `xu.windows.x64.exe` | `windows-x64` | PE32+ x86-64 |
| `xu.windows.arm64.exe` | `windows-arm64` | PE32+ ARM64 |

## 本机选用

在仓库根（或把对应二进制加入 `PATH`）：

```bash
# Apple Silicon macOS
XU=./developer/bin/xu.macos.arm64

# Intel macOS
XU=./developer/bin/xu.macos.x64

# Linux / Windows 同理换文件名
```

编示例：

```bash
$XU build ../xu-examples/examples/01_hello/main.xu
./main.xin
```

默认产物：mac/linux 为 `<stem>.xin`（已带可执行位，无需 `chmod +x`）；Windows 为 `<stem>.exe`。 
也可用 `-o` / `--output`（PowerShell 请用 `--output`）。

Windows（含 ARM 设备）：

- 优先用 **`xu.windows.arm64.exe`**（原生）；`xu.windows.x64.exe` 靠模拟也能跑，但更慢。
- 示例位于独立仓库 `xu-examples/examples`；编译时给出其目录或绝对路径。
- 成功时应看到：`wrote main.exe (windows-arm64)` / `(windows-x64)`。
- 若没有任何输出却出现了 `main.xin`，说明默认目标被当成了非 Windows——请换本目录最新 exe，或显式 `--target windows-arm64`。

## 重新打包

仓库根执行：

```bash
make xu # 或已有可用的 ./bin/xu
./scripts/pack_developer_xu.sh
```

需要已有可用的宿主 `bin/xu`，再用它交叉编出各平台产品编译器。 
`make xu` 定点后会另外把同一组二进制写到仓库根 `bin/platform/<os>-<arch>/xu`（Windows `xu.exe`）；本目录仍是 `xu.<os>.<arch>` 扁平快照，给分发和选种用。只重做 `bin/platform/`：`make xu-platform`。 
水印不在树内 Xu 源里。primer 编编译器时注入；自举链由产物二进制再注入。
