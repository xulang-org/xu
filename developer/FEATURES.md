# Xu 语言特色

<p align="center"><img src="../brand/xu_classic.svg" alt="Xu" width="88" height="88"></p>

Xu 把 一键静态编译部署与无 GC 内存安全**合成在一门系统语言里：写起来轻，跑起来可控，安全尽量在编译期过滤掉。

语法定稿见 [`docs/LANGUAGE.md`](../docs/LANGUAGE.md)；下面是给开发者看的「这门语言长什么样」。

---

## 三句话定调

| 目标 | 对标 | 你能直接感到的 |
|------|------|----------------|
| 极速编译与部署 | 说明 | 静态 AOT、单文件可执行、交叉编译一等公民、`xu build` 闭环 |
| 无 GC 的内存与线程安全 | | 所有权 + 借用；确定性 drop；无运行时 GC 抖动 |

**不是**：带 GC 的脚本语言，也不是「 换皮」。

---

## 语法上一眼能认出来的点

### 1. 控制流出口用符号，不是关键字

| 语句（写在语句首） | 含义 | 表达式里同形符号 |
|--------------------|------|------------------|
| `<<` / `<< expr` | 返回 | 左移 |
| `>> expr` | 抛出错误 | 右移 |
| `<<< expr` | 进程退出 | — |
| `<-` | break | channel 接收 |
| `->` | continue | — |
| `<->` | — | 可变参 `name <-> T`（展开/收成 `[]T`） |
| `:` | — | for/切片/match：半开 `[a, b)` |

没有用户面的 `return` / `break` / `continue` / `exit` 关键字。

### 2. 错误：`>>` + `or`，不要 `Result` / `?`

```xu
#errors

fn load(ok bool) string {
 if !ok { >> errors.new("fail") }
 << "ok"
}

s := load(false) or (err) {
 println(err.msg())
 << 1 // 或给左值赋默认值 / 再 >> 传播
}
```

- 强制处理：可能抛错的调用必须 `or`，或处于可传播上下文。
- `errors` 包只管错误值；语言提供 `>>` / `or` 机制。

### 3. 默认不可变；改写显式 `mut`

```xu
name := "Xu"
mut age := 20
age += 1
```

无全局可变变量。独占借用在调用点写 `mut &x`，类型上写 `&mut T`。

### 4. 包依赖是 `#路径`，不是 `import "..."`

```xu
@main
#errors
#strings
```

路径最后一段即包名：`#encoding/json` → `json.…`。

### 5. `any` 一词根，内部分流

| 写法 | 含义 |
|------|------|
| 裸 `any` | 动态盒；写一次；`is` / `as` |
| `名字# Bound` / `fn f#T` | 值泛型，编译期单态 |
| `struct@ Name` / `名字@ Bound` | 方法集约束（原 interface），默认静态分派 |

有匹配方法即满足约束，无需 `impl`。

### 6. 条件 / 循环无括号；区间 `:`（半开，切片 / match 同形）

```xu
if x > 0 { ... }
for i in 0:n { ... } // [0, n) → 0 .. n-1
for item in xs { ... }
while cond { ... }
match x {
 0:10 { ... } // [0, 10) → 0 .. 9
 10:20 { ... }
 else { ... }
}
```

### 7. 协程是 `xu f(args)`，不是 `go f(args)`

`chan` / `select` / 多核并发；关键字如下：

```xu
xu worker(1, ch) // ✅ 启动协程
xu worker(1, ch) // ❌ 不是 Xu；不用额外 spawn 关键字做 spawn
```

`xu.pkg.f(...)`（点号后）是包路径调用，不是 spawn。

---

## 内存与安全（无 GC）

- **所有权**：owning 值（`string`、`[]T`、含 owning 字段的 struct 等）按值传参即 move；作用域结束确定性 drop。
- **借用**：`&T` 共享、`&mut T` 独占；冲突在编译期拒绝。
- **切片拷贝语义**：`s[a:b]` / `xs[a:b]` 产生新拥有值，避免无 GC 下的共享视图别名。
- **越界 / 除零**：运行时 fail-loud（诊断后退出），不静默 wrap 成 UB。

---

## 工程形态

- 扩展名 `.xu`；入口 `fn main() int`（退出码）或 `fn main()`。
- 标准库使用顶层包名（`strings`、`os`、`net`…），实现走所有权，不暴露裸指针。
- 工具链：`build` / `check` / `fmt` / `test` / `install`；交叉 `--target macos-arm64|linux-x64|windows-x64|windows-arm64|…`。
- 自举：hosted gen3 即产品 `xu`；开发者目录提供各平台预编译 [`bin/xu.<os>.<arch>`](bin/)。

---

## 刻意不做（或后置）的

- 完整动态 OOP / 开放世界反射 
- 以 JIT 峰值吞吐为第一目标 
- 用户可见 `Result` / `Ok` / `Err` / `?` 
- 为了糖而破坏所有权可检查性 

---

## 和示例的对应

| 特色 | 示例 |
|------|------|
| 最小骨架、`<<` 退出 | [`examples/01_hello`](examples/01_hello) |
| 默认不可变 / `mut` / `const` | [`examples/02_bindings`](examples/02_bindings) |
| `<-` `->`、区间、`match` | [`examples/03_control_flow`](examples/03_control_flow) |
| struct + 方法、`&mut` 接收者 | [`examples/04_functions_methods`](examples/04_functions_methods) |
| `>>` + `or` | [`examples/05_errors`](examples/05_errors) |
| move / `&` / `mut &` | [`examples/06_ownership_borrow`](examples/06_ownership_borrow) |
| 数组、字符串切片拷贝、插值 | [`examples/07_arrays_strings`](examples/07_arrays_strings) |
| enum + match | [`examples/08_enum_match`](examples/08_enum_match) |
| `struct@`、`#T`、`any` | [`examples/09_generics_temp`](examples/09_generics_temp) |
| `xu` + `chan` | [`examples/10_concurrency`](examples/10_concurrency) |

使用细则见 [`USAGE.md`](USAGE.md)。
