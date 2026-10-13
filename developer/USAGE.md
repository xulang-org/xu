# Xu 语言使用帮助

<p align="center"><img src="../brand/xu_classic.svg" alt="Xu" width="72" height="72"></p>

本文按「怎么写日常代码」组织。先读 [`FEATURES.md`](FEATURES.md) 了解定位与特色记号；更细的规则见 [`docs/LANGUAGE.md`](../docs/LANGUAGE.md)。每节末尾链到 [`examples/`](examples/) 里对应可运行程序。

## 构建、运行与调试

普通 `build`、`run` 和 `test` 默认启用编译器经过验证的优化策略，无需选择优化等级：

```sh
xu build main.xu
xu run main.xu
xu test .
```

源码调试构建用 `--debug-build`：关闭 MIR 优化（含内联）和默认寄存器优化，同时生成 DWARF 行号与函数信息。这适用于 `build`、`run` 和 `test`。现有调试信息主要覆盖行号和函数，并不承诺完整的局部变量观察能力。

DWARF 输出目前支持 macOS 和 Linux 64 位目标。Windows PE、Linux ARM32 和裸机目标沿用现有后端能力：`--debug-build` 关闭优化，但不生成 DWARF。

```sh
xu build --debug-build main.xu
xu run --debug-build main.xu
xu test --debug-build .
```

`--no-opt` 单独关闭 MIR 优化和默认寄存器优化；原有 `--debug` 继续只添加调试信息，保留优化，适合分析实际运行的优化产物。`--debug-build` 等价于 `--no-opt --debug`。桌面打包由独立工具控制编译策略，目前拒绝这两个新增源码构建选项。

`-O0` 至 `-O3`、`--ra=0..3` 和 `--no-regcache` 保留为兼容及诊断选项。当前自动策略对应已验证的 O1，后续调整默认策略须通过正确性、编译成本和运行性能门禁。多个优化选择按最后一个 `-On`、`--no-opt` 或 `--debug-build` 生效；调试信息一旦启用仍然保留。显式 `--ra` 独立于优化选择，`--no-regcache` 始终关闭寄存器优化。例如 `--debug-build -O2` 生成带调试信息的 O2 产物。

`--timings` 还输出逐函数 `ra-fn:` 诊断：寄存器或缓存路径、回退阶段、标量驻留与栈存储数量、栈帧字节数、函数代码字节数，以及被拒绝的 MIR 指令和内存影响。诊断只观察编译过程，不改变输出程序；代码大小及静态栈统计不能直接换算为运行耗时。

---

## 1. 程序骨架

- 源文件扩展名：`.xu`，UTF-8。
- 可执行包第一行写包声明：`@main`（库包写 `@包名`，常与目录同名）。
- 入口：`fn main() int`（返回值作进程退出码）或 `fn main()`。
- **无分号**；条件 / 循环**无括号**。
- 依赖用行首 `#路径`，例如 `#errors`、`#strings`。包名是路径最后一段：`#encoding/json` → `json.Parse(...)`。

```xu
@main

#errors

fn main() int {
 println("hello")
 << 0
}
```

控制流出口用符号语句（表达式里同形符号仍是移位等）：

| 语句 | 含义 |
|------|------|
| `<<` / `<< expr` | 返回 |
| `>> expr` | 抛出 `errors.Error` |
| `<<< expr` | 进程退出 |
| `<-` | break（语句首、无操作数） |
| `->` | continue |

示例：[`examples/01_hello`](examples/01_hello)

---

## 2. 绑定与常量

默认**不可变**；要改写加 `mut`。

```xu
name := "Xu"
mut age := 20
age += 1

const Max = 100
```

- `:=` 推导类型；函数参数与返回类型须写明。
- `mut` 只修饰绑定，和类型上的 `&mut T` 不是一回事。
- 禁止全局可变变量；`const` 为编译期常量。

示例：[`examples/02_bindings`](examples/02_bindings)

---

## 3. 常用类型

| 类型 | 说明 |
|------|------|
| `int` | i64，默认整数 |
| `bool` | `true` / `false` |
| `string` | 双引号字面量；拥有型，切片拷贝 |
| `f64` | 浮点 |
| `i32` / `u32` / `u8` / `byte` | 独立窄整数；无隐式拓宽；算术 wrap |
| `[]T` | 动态数组 |
| `struct` / `enum` | 组合与标签联合 |
| `&T` / `&mut T` | 共享 / 独占借用 |
| `any` | 动态盒（写一次；`is` / `as`） |
| `map[string]int` 等 | 目前 intern 子集；见 LANGUAGE §4.7 |

字面量：`42`、`0xFF`、`0b1010`、`1_000_000`、`3.14`、`"hi"`、`` `多行` ``、`[1, 2, 3]`。

---

## 4. 控制流

```xu
if age >= 18 {
 println("adult")
} else {
 println("minor")
}

match age {
 0:13 { println("child") }
 13:20 { println("teen") }
 else { println("adult") }
}

for i in 0:5 { println(i) } // [0, 5)：0,1,2,3,4
for n in nums { println(n) }
while n > 0 { n -= 1 }
for { ... <- ... } // 无限循环 + break
```

字符串 `match` 必须有 `else`。`->` / `<-` 写在语句首。

示例：[`examples/03_control_flow`](examples/03_control_flow)

---

## 5. 函数、结构体与方法

没有 class：用 `struct` + 方法。

```xu
fn add(a int, b int) int {
 << a + b
}

struct Counter {
 n int
}

fn (c Counter) get() int { << c.n }

fn (c &mut Counter) inc() {
 c.n += 1
}
```

- 值接收者：只读语义。
- `&mut` 接收者：调用方绑定须为 `mut`，或已是 `&mut`。
- 字段默认**包内可见**；跨模块字段加 `pub` 或 `pub:` 区块。

示例：[`examples/04_functions_methods`](examples/04_functions_methods)

---

## 6. 错误处理：`>>` + `or`

**不要** `Result` / `Ok` / `Err` / `?` / 双返回值。

```xu
#errors

fn read_name(ok bool) string {
 if !ok {
 >> errors.new("empty")
 }
 << "ada"
}

fn main() int {
 s := read_name(false) or (err) {
 println(err.msg())
 << 1 // 在 main 里常直接退出
 }
 println(s)
 << 0
}

// 需要「失败给默认值」时，包一层返回 string 的函数：
fn load_or_fallback(ok bool) string {
 << read_name(ok) or (err) {
 println(err.msg())
 << "fallback"
 }
}
```

要点：

1. `>> expr` 抛出 `errors.Error`。
2. 调用后接 `or (名字) { ... }` 接住；名字自定。
3. 无 `or` 时错误向上传播；能到用户边界仍未处理 → 编译错误。
4. `or` 块内必须对左侧赋值，或用 `<<` / `<-` / `->` / `>>` / `<<<` 终止。
5. `err.msg()` 只读；`err is T` 判断；`err as T` 取出并销毁盒子。

示例：[`examples/05_errors`](examples/05_errors)

---

## 7. 所有权与借用

无 GC：每个 owning 值同一时刻一个所有者；离开作用域自动 drop。

```xu
fn take(s string) {
 println(s)
 // s 在此 drop
}

fn len_of(s &string) int {
 << s.len
}

fn append_bang(s &mut string) {
 s.push_str("!")
}
```

| 写法 | 含义 |
|------|------|
| 按值传 `string` / `[]T` / owning struct | **move** |
| `&x` | 共享借用 |
| `mut &x`（`x` 须 `mut`） | 独占借用 |
| `*r` | 解引用标量读/写（写需 `&mut`） |

共享借用存活期间不可写 / move / 再取 `&mut`；独占借用期间禁止冲突访问。

示例：[`examples/06_ownership_borrow`](examples/06_ownership_borrow)

---

## 8. 数组与字符串

```xu
mut xs := [1, 2, 3]
xs.push(4)
for x in xs { println(x) }

s := "hello"
println(s.len)
println(s[1:4]) // 拷贝切片，不是共享视图
println("hi $name") // 插值
```

- 索引越界、除零：运行时 fail-loud。
- `[]string` 的 for-in 会隐式克隆元素；其它 owning 元素规则见 LANGUAGE §5.4。

示例：[`examples/07_arrays_strings`](examples/07_arrays_strings)

---

## 9. Enum 与 match

```xu
enum Color {
 Red
 Green
 Rgb(int, int, int)
}

match c {
 Color.Red { ... }
 Color.Green { ... }
 Color.Rgb(r, g, b) { ... }
}
```

- 构造：`Color.Red`、`Color.Rgb(1, 2, 3)`。
- match 须穷尽或带 `else`。
- 泛型：`enum Opt#T { None, Some(T) }`（见 LANGUAGE §4.6）。
- owning 载荷的 match 会**消费**主体。

示例：[`examples/08_enum_match`](examples/08_enum_match)

---

## 10. 泛型、`struct@` 与 `any`

一词根 **`any`**，内部分流：

| 写法 | 含义 |
|------|------|
| 裸 `any` | 动态盒；`is` / `as` |
| `名字# Bound` / `fn f#T(...)` | 值泛型单态 |
| `struct@ Name` / `名字@ Bound` | 方法集约束（原 interface） |

```xu
struct@ ToString {
 fn to_string() string
}

fn print_item(item# ToString) {
 println(item.to_string())
}

fn identity#T(x T) T { << x }

let n: any = 42
println(n is int)
v := n as int
```

有匹配方法即满足约束，无需 `impl`。动态装箱对用户 `struct@` 已可用（闭世界 itable）；日常优先静态 `item# I`。

示例：[`examples/09_generics_temp`](examples/09_generics_temp)

---

## 11. 并发（`xu` / `chan`）

```xu
fn worker(id int, ch chan int) {
 ch <- id * 10
}

fn main() int {
 ch := chan int{cap: 1}
 xu worker(1, ch)
 println(<-ch)
 << 0
}
```

- `xu f(args)` 启动协程（**不是** 的 `go f(args)`）；`xu.pkg.f` 是包路径调用，不是 spawn。
- Channel 转移所有权；不要把借用送进协程。
- `select`、无缓冲会合、`close` 见 LANGUAGE §7 与 fixtures。

示例：[`examples/10_concurrency`](examples/10_concurrency)

---

## 12. 模块与工具链速查

预编译各平台 gen3 见 [`bin/`](bin/)：`xu.<os>.<arch>`（Windows 为 `xu.windows.<arch>.exe`，如 `xu.macos.arm64`、`xu.linux.x64`、`xu.windows.x64.exe`）。

```bash
XU=./developer/bin/xu.macos.arm64 # 按平台替换
$XU build file.xu # 编单个文件，默认 -O1 写到 cwd/<stem>（Windows 加 .exe）
$XU build file.xu -o out # 指定产物路径
$XU build file.xu -O0 # 调试档：关 MIR 形变与 RA（比 检查器 -Copt-level=0 更贴源码）
$XU build file.xu -O1 # 默认档：折叠/叶内联/倒置/BCE + ALU 块 CSE + 块内 RA
$XU build file.xu -O2 # 发布档：再开 SimplifyCFG / 无环内联 / load-LICM；RA 为 greedy + CSR
$XU build file.xu -O3 # 与 O2 同一套 MIR/RA 算法，只抬 unroll/内联门槛与环 pin
# --no-regcache 只关寄存器缓存，不影响 MIR 档（默认仍是 -O1）
$XU build <dir> # 目录必须有 xu.xun；编其中全部 *.xu（不递归），默认 cwd/<dirname>
$XU run <dir|file.xu> [-- args...] # 类似 xu run：编译后直接执行（仅本机 target）
$XU check main.xu # 仅解析+类型+借用；末尾列死循环风险与退出位点
$XU fmt file.xu [-w] # 格式化
$XU map [path...] # 源码流程图（默认 Mermaid；--graph 给画布）；亦可 xu-map
$XU doc [path...] [-o file] # 声明文档 Markdown；亦可 xu-doc
$XU test file.xu... # 只跑 test.<名>.xu 里的 fn test_*()
# 测试组件：test.<方法名>.xu（≥3 节）；普通源码禁止命名 fn test_*
# 目录 build/check：跳过 test.*.xu（同 go build 跳过 *_test.go）；显式文件路径照编；仅 xu test 目录模式纳入测试组件
# 旗标：-run REGEXP -v -count N -failfast -list -short -bench REGEXP
# bootstrap：xu --test file.xu …（同一套旗标）
```

默认编本机（`--target` 未写时看 `XUOS`/`XUARCH`，再看正在运行的编译器二进制）。交叉编译：`--target linux-arm64` 或 `XUOS` / `XUARCH`。

多文件：同目录同一包；`#util` 加载 `util/*.xu` 或 `util.xu`。对外可见声明加 `pub`。

---

## 13. 常见坑（速记）

1. **返回写 `<<`，不是 `return`**；break/continue 是 `<-` / `->`。
2. **错误用 `>>` + `or`，不要 `Result`/`?`。**
3. **默认不可变**；改绑定加 `mut`，独占借用写 `mut &x`。
4. **字符串切片是拷贝**，不是共享视图。
5. **区间用 `:`**（半开 `[start, end)`），不是 `0..n`，也不是 `0 -> n` 或 `0...9`。
6. **`or` 只接错误**；布尔或用 `||`。
7. **import 写 `#errors`**，不是 `import "errors"`。

规范全文与诚实实现清单：[`docs/LANGUAGE.md`](../docs/LANGUAGE.md) §0.1、§12。
