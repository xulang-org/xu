# Xu 操作系统级开发架构与工程实施全套方案

> **文件版本**：v1.0.0  
> **状态**：已立项 / 实施中 (In Progress)  
> **核心原则**：严格坚守**零 GC 确定性析构**、**隐式所有权推导（无手写生命周期标注）**与**类 Go 直觉开发体验**；底层通过**分层架构（Layered Architecture）**与**严格隔离的底层硬件契约**支撑内核、驱动与裸机固件开发。

---

## 一、 总体分层架构 (Layered Architecture)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 用户态应用 / 云原生微服务 (Default Profile: std)                               │
│ · 语法体验：隐式所有权推导、零 GC、`<<`/`>>` 符号流控、`$` 可变绑定、`>>>` 错误处理  │
│ · 并发机制：原生 `xu worker()` 协程 + `chan` 类型化通道、工作窃取调度器 (M:N)       │
│ · 运行时：自动堆内存管理、I/O 事件循环 (epoll/kqueue/IOCP)、宿主系统调用抽象        │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ 依赖底层基础库
┌──────────────────────────────────────▼──────────────────────────────────────┐
│ 操作系统内核 / 驱动 / 裸机固件 (Freestanding Profile: --profile=freestanding)  │
│ 1. 核心库解耦：`core` (纯计算/位操作/借用推导/内存布局) 与 `std` (宿主系统调用) 彻底剥离 │
│ 2. 硬件契约隔离：`unsafe { ... }`、裸指针 `*raw T`，仅在底层 5% 硬件映射代码中启用   │
│ 3. 硬件交互原语：Volatile MMIO 读写屏障、内联汇编 `asm!`、裸函数 `#[naked]`、对齐属性│
│ 4. 可插拔基础设施：自定义物理页/堆分配器 (`GlobalAlloc`)、中断安全自旋锁 (`IrqSpinlock`) │
│ 5. 驱动协程降级：编译期状态机消除 (`CoroElide`)，无栈纯静态调度，零外部调度器依赖   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、 编译器与代码库改造全景映射 (Codebase Mapping)

本方案直接基于 Xu 编译器目前的自举架构（`xu/src/`）进行模块化解耦与增强：

| 编译器模块路径 | 当前职责 | 操作系统级支持改造点 |
| :--- | :--- | :--- |
| `src/xu/token/token.xu` | 词法 Token 定义 | 增加 `TOK_KW_UNSAFE`、`TOK_ASM`、`TOK_RAW`（裸指针）、`TOK_VOLATILE` 等关键字标识 |
| `src/xu/parser/` | 语法解析 (`declarations`, `statements`, `ffi`) | 解析 `asm!(...)` 内联汇编表达式、`*raw T` 裸指针类型、`#[no_mangle]`、`#[naked]`、`#[section("...")]`、`#[panic_handler]` 等编译属性 |
| `src/xu/ast/ast.xu` | AST 语法树节点定义 | 扩充 `NK_INLINE_ASM`、`NK_VOLATILE_READ`、`NK_VOLATILE_WRITE`、`NT_RAW_PTR` 节点 |
| `src/xu/types/` | 类型系统与符号表 | 引入裸指针类型 `RawPtrType`，处理裸指针与整型之间的显式转换 |
| `src/xu/checker/` | 语义与类型检查 | 强化 `unsafe` 检查：凡是解引用 `*raw T` 或调用 `asm!` 必须置于 `unsafe` 作用域内 |
| `src/xu/borrow/` | 隐式生命周期与借用检查 | **零侵入**：借用推导图完全跳过 `*raw T`，不干扰上层引用 `&T` 和 `$&T` 的生命周期推导 |
| `src/xu/mir/mir.xu` | 中间表示与优化 Pipeline | 新增 MIR 操作码 `MirOp::InlineAsm`、`MirOp::VolatileLoad`、`MirOp::VolatileStore`；优化器严禁对 volatile 节点进行 DSE（死代码消除）和跨屏障重排 |
| `src/xu/codegen/` | 架构后端与机器码发射 (`x64`, `arm64`, `rv64`) | 1. `regalloc.xu` 支持内联汇编寄存器约束绑定；<br>2. `frame.xu` 识别 `#[naked]` 抑制栈帧生成；<br>3. 实现段选择（`.text.boot`）代码发射 |
| `src/xu/driver/driver.xu` | 编译器 CLI 与编译管线 | 增加 `--profile=freestanding`（或 `--no-std`）与 `--linker-script` 参数，阻断默认 host 运行时注入 |
| `src/runtime/` | 运行时核心 | 拆分为独立无依赖的 `src/core/` 库（纯计算、数据结构、格式化）与保留宿主特性的 `src/std/` 库 |

---

## 三、 三阶段工程实施路线图

### 阶段一：裸机最小可行内核（Freestanding PoC）

#### 1. 核心目标
在 QEMU（x86_64 与 riscv64）模拟器中成功引导无宿主依赖的裸机二进制镜像，通过串口（UART COM1 0x3F8 / 0x10000000）打印出启动日志，验证编译工具链闭环。

#### 2. 具体任务清单
- [x] **Task 1.1: 架构与技术演进方案归档入库**
  - 将本规划与架构技术规范归档于代码库 `docs/design/OS_ARCHITECTURE_PLAN.md` 与根目录 `OS_IMPLEMENTATION_PLAN.md`。
- [x] **Task 1.2: 编译器 CLI 增加 Freestanding Profile 支持**
  - 修改 `src/xu/driver/driver.xu`：解析 `--profile=freestanding` / `--no-std`。
  - 在 freestanding 模式下，跳过注入 `host_win.xu`、`host_proc.xu`、`host_net.xu`、`chan.xu` 等系统调度组件。
- [x] **Task 1.3: 段定义与符号属性控制**
  - 支持 `#[no_mangle]`：取消 C 符号名字重整。
  - 支持 `#[section(".text.boot")]`：将引导函数放置在链接段头部。
  - 支持 `#[naked]`：在 `src/xu/codegen/frame.xu` 中跳过栈帧初始化与清理指令。
- [x] **Task 1.4: 内联汇编（Inline Assembly）AST 与代码生成**
  - 语法定义：`unsafe { asm!("instruction", in(reg) a, out(reg) b, options(...)); }`。
  - 在 `src/xu/ast`、`src/xu/mir` 与 `src/xu/codegen` 中打通直达机器指令的通道。
- [x] **Task 1.5: 裸机 Panic 挂钩机制**
  - 支持 `#[panic_handler]` 修饰发散返回类型的处理函数 `fn (info: &PanicInfo) -> !`。
- [x] **Task 1.6: 裸机验证工程（`examples/baremetal/kernel_poc`）**
  - 提供链接脚本 `linker.ld`。
  - 编写多架构引导启动源码，配置 `make qemu` 自动化启动与测试断言。

---

### 阶段二：硬件抽象契约与内存分页（HAL & Memory Management）

#### 1. 核心目标
建立严格隔离的硬件交互抽象层（HAL）。通过裸指针类型系统、Volatile 访问屏障、结构体精确对齐控制与可插拔全局分配器，实现内核虚拟内存分页管理与中断向量表接管。

#### 2. 具体任务清单
- [x] **Task 2.1: 裸指针类型 `*raw T` 与 `unsafe` 隔离块**
  - 语法与 AST 扩充：`NT_RAW_PTR`、`TYPE_KIND_RAW_PTR`。
  - 允许整数物理地址强制转换为裸指针：`addr as *raw u32`，以及引用转裸指针 `&v as *raw T`。
  - 解引用 `*ptr` 与裸指针赋值 `*ptr = val` 必须在 `unsafe { ... }` 块内执行，语义分析阶段严格校验。
  - `src/xu/borrow` 借用推导完全跳过 `*raw T`，确保应用层常规引用的全自动推导零退化。
- [x] **Task 2.2: 结构体内存排布属性（`#[repr(...)]`）**
  - 完善 `@repr("C")`、`@repr(packed)`、`@align(N)`、`@repr("C", align: N)` 属性解析与布局计算。
  - `checker/layout.xu` 精确按目标架构 ABI 发射结构体字段偏移与内存填充（Padding），紧凑排布无填充。
- [x] **Task 2.3: 易失性 MMIO 访问（Volatile）内建函数**
  - 引入编译器内建 `volatile_read(ptr)` 与 `volatile_write(ptr, val)`。
  - 扩展 MIR 指令 `MI_VOLATILE_LOAD` 与 `MI_VOLATILE_STORE`，DCE 与 LICM 严密设防，阻止优化消除或提升。
  - 完成 x86_64、AArch64、RISC-V 机器码发射与寄存器分配器对接。
- [x] **Task 2.4: 拆分 `core` 纯静态子集库**
  - 创建独立无宿主依赖的 `src/core/` 库：
    - `src/core/arch/mod.xu`: 硬件特权指令 (`cli`, `sti`, `hlt`, `pause`, `wfi`, `in8`, `out8`)
    - `src/core/mem/mod.xu`: 零依赖内存原语 (`memset`, `memcpy`, `memcmp`)
    - `src/core/alloc/mod.xu`: `Layout`、`layout_new` 与 `GlobalAlloc` 接口规范
    - `src/core/sync/mod.xu`: 裸机中断安全自旋锁 `Spinlock`
- [x] **Task 2.5: 可插拔物理/堆分配器接口（`GlobalAlloc`）**
  - 定义 `GlobalAlloc` 接口契约，支持裸机内核注入全局页分配器或 Slab 内存池。
- [x] **Task 2.6: 自举闭环与多架构裸机 PoC 验证**
  - 验证三代完全自举收敛（3-generation self-hosting deterministic bootstrap convergence，Gen2 与 Gen3 SHA-256 逐位一致）。
  - `examples/baremetal/kernel_poc` 成功编译为 `kernel_x64.elf`、`kernel_arm64.elf`、`kernel_rv64.elf`，无符号未决错误。

---

### 阶段三：抢占调度、并发同步与多任务上下文切换（Multitasking & Context Switching）

#### 1. 核心目标
完成裸机内核多任务抢占式与协作式任务切换、中断安全并发原语（`Spinlock`、`IrqSpinlock`）、RAII 确定性析构守卫（`SpinGuard`、`IrqGuard`），并打通多架构上下文切换汇编（x86_64、AArch64、RISC-V 64）。

#### 2. 具体任务清单
- [x] **Task 3.1: 内核自旋锁与中断安全同步原语（`#core/sync`）**
  - 实现 `Spinlock` 与 `IrqSpinlock`（加锁前执行 `arch.cli()` 关中断并记录嵌套深度 `depth`，解锁在深度归零时执行 `arch.sti()` 开中断）。
  - 利用 Xu 确定性析构（Deterministic Destruction）实现 `SpinGuard` 与 `IrqGuard` 的 `drop()` 方法，离开作用域自动安全解锁，**零 GC 运行时开销**。
  - 适配借用检查器的局部根约束：在解引用的裸指针上直接执行 volatile 读写，规避可变方法调用的所有权根限制。
- [x] **Task 3.2: 跨架构任务上下文切换（`#core/task`）**
  - 定义跨平台 192 字节 16 字节对齐的 `TaskContext` 结构体（`@repr("C", align: 16)`），包含通用被调用者保存寄存器（Callee-saved registers）、帧指针（`fp`）、指令指针（`pc`）、栈指针（`sp`）。
  - 提供人体工学初始化方法 `TaskContext.init(entry u64, stack_top u64)`，自动按 16 字节向下对齐栈顶并预留函数调用开场偏移。
  - 为 x86_64、AArch64、RISC-V 64 三大架构手写并集成原子上下文切换汇编入口 `switch_context(prev *raw TaskContext, next *raw TaskContext)`。
  - 封装安全上下文切换 API `task_switch(prev $&TaskContext, next &TaskContext)`。
- [x] **Task 3.3: Freestanding 模式下的静态 C ABI 符号调用**
  - 改造 `src/xu/ffi/ffi.xu`：允许 `*raw T` 跨越 C ABI 边界作为参数或 `@repr("C")` 结构体字段。
  - 改造 `src/xu/mir/lower_ffi.xu`：在 `w.tgt_os == 3`（`OS_NONE` 裸机目标）下，将 `extern "C"` 函数直接降级为静态符号调用 `w.call(sym, &args)`，彻底摆脱用户态宿主 `ffi_sym` / `ffi_call` 动态符号查找。
- [x] **Task 3.4: 裸指针与函数指针类型转换与比较运算**
  - 改造 `src/xu/checker/expr.xu`：支持命名函数向 `*raw T`、`u64`、`int` 的直接强转，支持同类型裸指针比较（`==`、`!=`、`<`、`>`、`<=`、`>=`）。
  - 改造 `src/xu/mir/lower.xu`：`NK_TYPE_AS` 处理函数转换时直接发射 `MI_LOAD_FN_ADDR` 获取静态符号入口地址；解引用裸指针时正确解包目标内部类型，避免结构体字段访问错误。
- [x] **Task 3.5: 多文件 AST 合并（`merge_from`）对齐防篡改**
  - 修复 `src/xu/parser/parser.xu` 中 `merge_from` 遍历语法树时的节点重定位漏洞：豁免 `ast.NK_FFI` 节点的自定义对齐字段 `c`、`d`、`e`，防止将对齐值（如 16）误当成子节点索引加上偏移量变为非法非 2 的幂（如 5016）。
- [x] **Task 3.6: 多架构裸机多任务内核 PoC 验证**
  - 在 `examples/baremetal/kernel_poc/main.xu` 中构建完整演示：
    - 主任务初始化 4KB 对齐的 `PageTable`，配置 2MB 恒等映射（Identity Mapping）。
    - 验证紧凑网络包头 `EthernetHeader`。
    - 初始化 Task 1（栈 `0x00211000`）与 Task 2（栈 `0x00221000`）。
    - 主任务切换至 Task 1；Task 1 测试 RAII `IrqSpinlock`，切至 Task 2；Task 2 测试 RAII `Spinlock`，切回主任务。
    - 主任务验证执行状态，输出全部断言成功日志，cleanly halt CPU。
  - 三架构裸机 ELF 编译全部通过，0 错误，0 未决符号：
    - `kernel_x64.elf` (x86_64): 23,728 bytes
    - `kernel_arm64.elf` (AArch64): 11,048 bytes
    - `kernel_rv64.elf` (RISC-V 64): 66,456 bytes
  - 三代确定性自举收敛校验通过（Gen2 == Gen3 SHA256: `779D5B5393EFF571F438D34CBC68A74AC55D693CC72DB4F8F3B49682D4A3D070`）。

---

### 阶段四：高级操作系统生态、驱动与中断体系（Advanced OS Architecture）

#### 1. 核心目标
构建完整的中断描述符表（IDT / Vector Table）、时钟中断抢占调度器、系统调用分发（Syscall / Sysret）以及硬件虚拟化外设驱动（VirtIO），提供完整的操作系统脚手架。

#### 2. 具体任务清单
- [x] **Task 4.1: 中断处理与 TrapFrame 异常分发（`#core/arch` & `#core/task`）**
  - 定义完整的异常中断上下文 `TrapFrame`（16 字节对齐，精确按架构 ABI 保存 `r15..r8`、`rbp`、`rdi`、`rsi`、`rdx`、`rcx`、`rbx`、`rax`、中断向量号 `vec`、错误码 `error_code` 以及 CPU 压栈的 `rip`、`cs`、`rflags`、`rsp`、`ss`）。
  - 实现 x86_64 16 字节中断门描述符 `IdtEntry` 与 10 字节紧凑 IDTR 指针结构体 `IdtPointer`（`@repr("C", packed)`），以及门描述符属性配置方法 `set_gate`。
  - 在底层代码生成器中发射原子指令桩：`load_idt`（`lidt [rdi]`）、`set_vbar`（ARM64 `msr vbar_el1, x0`）、`set_trap_vector`（RISC-V 64 `csrw stvec, a0`）。
- [x] **Task 4.2: 时钟中断抢占式调度基础设施**
  - 实现 8259A 可编程中断控制器重映射驱动 `pic_remap(offset1, offset2)`，将硬件 IRQ 0..15 映射至 IDT 向量 32..47，彻底规避 CPU 0..31 异常冲突。
  - 实现中断结束确认信号分发 `pic_eoi(irq)` 与中断屏蔽 `pic_disable()`。
  - 实现 8254 可编程定时计数器初始化函数 `pit_init(freq_hz)`，以 Mode 3 速率发生器模式向 0x43 端口配置除数，生成周期性硬件中断脉冲。
- [x] **Task 4.3: 硬件寄存器控制与系统调用入口**
  - 在 `src/xu/codegen/x64_base.xu`、`arm64_base.xu`、`rv64_base.xu` 中原生发射底层特权级操作接口：
    - 页表基址与缺页地址访问：`read_cr3()`、`read_cr2()`、`write_cr3(val)`、`invlpg(addr)`。
    - 快速端口 I/O：`in8`、`out8`、`in16`、`out16`、`in32`、`out32`。
    - 系统调用返回入口 `syscall_entry`（x86 `sysretq`、ARM64 `eret`、RISC-V `sret`）。
- [x] **Task 4.4: 多架构裸机内核 PoC 验证与自举收敛**
  - `examples/baremetal/kernel_poc/main.xu` 集成 Stage 4 全套中断与硬件控制验证：
    - 初始化 PIC 重映射与 PIT 100 Hz 时钟发生器；
    - 配置 IDT 32 号中断门指向 `timer_interrupt_isr`；
    - 执行 `load_idt` 成功加载 IDTR 描述符；
    - 验证 `read_cr3()` 寄存器直读与 `TrapFrame` 初始化；
    - 验证 `VirtioBlkDriver` 与 `VirtioNetDriver` 实例探测；
  - 三架构裸机 ELF 编译全部成功，0 错误，0 警告：
    - `kernel_x64.elf` (x86_64): 31,801 bytes
    - `kernel_arm64.elf` (AArch64): 16,104 bytes
    - `kernel_rv64.elf` (RISC-V 64): 86,864 bytes
  - 三代确定性自举收敛验证通过（Gen3 == Gen4 SHA-256: `70A53F14DD80C9D378F3A1F151F442BE1083DC57B862FE1CE4E0B020CBCFF56C`）。
- [x] **Task 4.5: VirtIO 虚拟化外设设备驱动实装（`#core/virtio`）**
  - 实现纯静态无依赖的 VirtIO MMIO 驱动框架：
    - 设备探测与协商：`VirtioDevice.probe()`、`init_device()`，设备状态机（Reset -> Ack -> Driver -> Features -> Driver_OK）。
    - VirtQueue 描述符环结构：16 字节 `VirtqDesc`、8 字节 `VirtqUsedElem`、`VirtqAvail`。
    - VirtIO-Blk 驱动（`VirtioBlkDriver`）：请求头 `VirtioBlkReq`、容量读取与扇区读写接口。
    - VirtIO-Net 驱动（`VirtioNetDriver`）：报文头 `VirtioNetHdr`、MAC 地址读取与网络包收发接口。
- [x] **Task 4.6: 官方裸机开发脚手架（`xu init --baremetal` / `xu new --baremetal`）**
  - 在编译器 CLI 驱动（`src/xu/driver/driver.xu`）中内置裸机脚手架生成器：
    - 支持 `xu init --baremetal [name]` 与 `xu new --baremetal [name]` 一键初始化；
    - 自动生成 `xu.xun`（声明 `profile: freestanding`）；
    - 自动生成 starter `main.xu`（带 `$freestanding`、`#core/*`、串口驱动与启动入口）；
    - 自动生成 `linker.ld`（标准段布局与 64KB 引导栈）；
    - 自动生成 `Makefile`（多架构 `x64-none`、`arm64-none`、`riscv64-none` 构建与 `make qemu` 启动目标）；
    - 脚手架工程实测一键编译通过，生成纯净裸机内核镜像（x86: 1.9KB, arm64: 2.4KB, rv64: 2.4KB）。
- [ ] **Task 4.7: 驱动协程降级优化（CoroElide 无栈状态机）**
  - 在 `freestanding` 模式下，针对标记为异步的设备驱动函数，编译器将其转为静态状态机。
  - 消除对用户态调度池的依赖，由内核时钟中断或硬件中断下半部统一轮询驱动。

---

## 四、 阶段一核心规范与代码设计示例

### 1. 最小裸机内核入口规范 (`src/main.xu`)

```xu
// 声明裸机无宿主模式
#![no_std]

#core/arch

// 裸机 Panic 处理器（发散函数，永不返回）
#[panic_handler]
fn on_panic(info: &PanicInfo) -> ! {
    serial_print("[KERNEL PANIC] CPU halted: ")
    serial_print(info.message)
    loop {
        arch.halt() // 汇编 hlt / wfi 指令
    }
}

// 串口写字符（使用内联汇编直接操作 x86 COM1 端口）
fn uart_putc(c: u8) {
    unsafe {
        asm!(
            "out dx, al",
            in("dx") 0x03F8 as u16,
            in("al") c,
            options(nostack, nomem)
        )
    }
}

fn serial_print(msg: string) {
    let $i := 0
    while i < msg.len {
        uart_putc(msg[i])
        i = i + 1
    }
}

// 引导入口函数：裸函数，禁止编译器生成默认栈帧
#[naked]
#[no_mangle]
#[section(".text.boot")]
fn _start() -> ! {
    unsafe {
        // 加载临时内核栈顶指针
        asm!(
            "lea rsp, [rip + _stack_top]",
            options(nostack)
        )
    }

    // 打印启动横幅
    serial_print("\n========================================\n")
    serial_print("  Welcome to Xu Baremetal Kernel (v0.1) \n")
    serial_print("  Zero-GC Deterministic Destruction!     \n")
    serial_print("========================================\n\n")

    // 挂起 CPU
    loop {
        arch.halt()
    }
}
```

### 2. 裸机链接脚本规范 (`linker.ld`)

```ld
ENTRY(_start)

SECTIONS {
    /* 内核加载到 1MB 物理内存处 */
    . = 1M;

    .text.boot : {
        *(.text.boot)
    }

    .text : {
        *(.text .text.*)
    }

    .rodata : {
        *(.rodata .rodata.*)
    }

    .data : {
        *(.data .data.*)
    }

    .bss : {
        *(.bss .bss.*)
        . = ALIGN(4096);
        _stack_bottom = .;
        . += 16K; /* 预留 16KB 引导栈 */
        _stack_top = .;
    }
}
```

---

## 五、 质量保证与零退化验证原则

1. **零退化铁律**：
   - 现有的 72 项性能基准测试（Benchmarks）、用户态单元测试与协程高并发测试必须 **100% 保持绿色，且无任何吞吐量或内存退化**。
   - 所有为操作系统引入的底层机制（`unsafe`、`*raw T`、`asm!`）必须被严格限制在 `unsafe` 语义边界内，常规应用开发体验维持绝对简洁。
2. **双轨 CI 体系**：
   - **Track A (User-space)**：监控现有编译器自举与标准库功能。
   - **Track B (Baremetal)**：在 GitHub Actions 中配置 QEMU，自动化构建并运行 Baremetal 内核测试，通过捕获串口输出验证断言。
