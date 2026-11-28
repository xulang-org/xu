<p align="center">
  <a href="https://xulang.org/zh-tw/"><img src="brand/xu_classic.svg" alt="Xu Logo" width="100" height="100"></a>
</p>

<h1 align="center">Xu 程式語言</h1>

<p align="center">
  <b>兼具 Go 的直覺併發與 C/Rust 的零 GC 極致效能</b><br>
  <sub>專為高效能低延遲系統、微服務底層與現代輕量級應用打造的編譯期記憶體安全語言</sub>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">简体中文</a> | <b>繁體中文</b> | <a href="README.ja.md">日本語</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a> | <a href="README.ru.md">Русский</a> | <a href="README.pt-BR.md">Português</a>
</p>

<p align="center">
  <a href="https://github.com/xulang-org/xu/releases"><img src="https://img.shields.io/github/v/release/xulang-org/xu?label=Release&color=0284c7" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-emerald.svg" alt="License"></a>
  <a href="https://xulang.org/zh-tw/"><img src="https://img.shields.io/badge/Docs-xulang.org-rose" alt="Docs"></a>
  <a href="https://xulang.org/zh-tw/benchmarks/"><img src="https://img.shields.io/badge/Benchmarks-72%20Workloads-amber" alt="Benchmarks"></a>
  <a href="https://github.com/xulang-org/xu/actions/workflows/sdk.yml"><img src="https://github.com/xulang-org/xu/actions/workflows/sdk.yml/badge.svg" alt="SDK CI"></a>
</p>

<p align="center">
  <a href="https://xulang.org/zh-tw/playground/">🌐 <b>線上演練場（免安裝試玩）</b></a> &nbsp;•&nbsp;
  <a href="https://xulang.org/zh-tw/benchmarks/">⚡ <b>72 項跨語言基準看板</b></a> &nbsp;•&nbsp;
  <a href="#quick-start">🚀 <b>30 秒上手</b></a> &nbsp;•&nbsp;
  <a href="RELEASES.zh-CN.md">📋 <b>版本說明</b></a> &nbsp;•&nbsp;
  <a href="https://github.com/xulang-org/xu/releases">📦 <b>下載安裝套件</b></a>
</p>

---

> **官方 SDK 下載**：[GitHub Releases](https://github.com/xulang-org/xu/releases) — 完整更新紀錄、破壞性變更與遷移指南請參閱 [版本說明 (Release Notes)](RELEASES.zh-CN.md) 或 [英文版 (RELEASES.md)](RELEASES.md)。

## ⚡ 一眼看懂 Xu（Show, Don't Tell）

無需繁雜設定，也不必背誦晦澀的生命週期標註。用 15 行程式碼感受 Xu 的現代語法風格：

```xu
@main
#errors

// 符號化流程控制：<< 回傳、>> 拋出錯誤；告別 Result/unwrap 巢狀樣板
fn fetch_metric(task string) int {
    if task.len == 0 { >> errors.new("empty task name") }
    << task.len * 42
}

fn worker(task string, ch chan int) {
    val := fetch_metric(task) >>> (err) { << } // 強制就地安全處理，不再充斥 if err != nil
    ch <- val                                 // 型別安全的通道訊息傳遞
}

fn main() int {
    ch := chan int{cap: 2}
    xu worker("latency", ch) // 原生 xu 關鍵字啟動輕量級協程
    xu worker("memory", ch)
    println(<-ch + <-ch)     // 通道匯聚輸出
    << 0                     // 確定性釋放、零 GC 停頓、純靜態原生 AOT 編譯
}
```

> **開發者喜愛的核心亮點**：
> 1. **符號化流程控制**：`<<` 回傳、`>>` 拋錯、`<<<` 退出，告別冗長關鍵字。
> 2. **優雅的錯誤流**：在呼叫點透過 `>>> (err) { ... }` 強制安全處理或透過 `>>>` 傳播，消除滿屏 `if err != nil` 與 `unwrap()` 執行期崩潰風險。
> 3. **原生輕量級併發**：`xu worker()` 協程搭配 `chan` 通道，帶來如同 Go 一般直覺的併發心智模型。
> 4. **編譯期靜態安全**：基於所有權與借用推導，**無垃圾回收器（Zero-GC）**，零停頓且記憶體極度精簡。

可寫參考名稱 `r: $&T` 可滿足 `&T` 的預期：直接寫 `read(r)` 或 `let view: &T = r`。共享檢視及其衍生值存活至最後一次使用為止，期間會凍結父參考並拒絕衝突的寫入與移動，包含已儲存的檢視與呼叫回傳值。同一呼叫中衝突的共享與可寫引數會被拒絕。隱式降級目前要求為區域參考名稱且直接指向型別完全相同。可變繫結僅需在宣告處標記一次：`$x := value` 或 `let $x: T = value`，之後使用普通名稱 `x` 即可。普通值的共享借用寫作 `&x`，可寫借用寫作 `$&x`，對應的參考型別為 `$&T`。重複使用參考名稱直接寫 `r`，顯式再借用寫作 `&*r`；普通值的自動借用尚未實作。
底層硬體與裸機契約：作業系統核心與裝置驅動透過裸指標 `*raw T` 操作，解參考必須置於顯式 `unsafe { ... }` 區塊中（例如 `p := addr as *raw u32; unsafe { *p = val }`），借用推導完全略過裸指標；MMIO 存取使用內建 `volatile_read` / `volatile_write` 記憶體屏障；結構體排布支援 `@repr("C", align: N)` 精確對齊與 `@repr("C", packed)` 零填充緊湊排布；裸機原始碼以 `$freestanding` 徹底切斷宿主系統呼叫與 libc 相依。

現行借用與底層契約規則請見 [借用與記憶體模型指南](https://xulang.org/zh-tw/docs/lang/memory/)。

---

## 🎯 痛點與「Why Xu?」

在建構高效能系統與服務時，工程師往往被迫在缺陷重重的權衡之間二選一：

### 1. 我們解決的真實困境

- **痛點一：垃圾回收（GC）的延遲抖動與記憶體膨脹**
  - *現狀*：Go 與 Java 開發效率高，但 GC 的 STW 停頓與不可預測的延遲尖峰，在低延遲閘道器、交易引擎與嵌入式目標中往往是致命瓶頸。
  - *Xu 解法*：**零 GC 執行期**。純 AOT 編譯，編譯期透過所有權模型追蹤記憶體並於作用域結束時確定性釋放。零停頓、零 GC 抖動。
- **痛點二：記憶體安全與「顯式生命週期標註地獄」的拉鋸**
  - *現狀*：C/C++ 手動管理記憶體容易造成懸空指標、記憶體破壞與 UAF 漏洞；Rust 雖然安全，但顯式生命週期參數（`'a`、`'b`）與繁雜的型別體操顯著拖慢開發節奏。
  - *Xu 解法*：**隱式所有權推導與借用檢查**。業務程式碼無需手寫顯式生命週期標註，切片天然採值語意隔離，兼顧安全與開發速度。
- **痛點三：滿屏樣板程式碼與層層嵌套的錯誤包裝**
  - *現狀*：Go 專案充斥重複的 `if err != nil`；Rust 則常將型別層層包裹在 `Result<T, E>` / `Option` 之中。
  - *Xu 解法*：**符號流 `>>` 搭配強制 `>>> (err) { ... }`**，提供輕量、簡潔且安全的錯誤傳播機制。
- **痛點四：工具鏈碎片化與環境建置阻力**
  - *現狀*：拼裝 CMake、Make、套件管理器與各平台連結器向來脆弱且費時。
  - *Xu 解法*：**單一二進位閉環**。編譯器、測試執行器、格式化工具（`xu fmt`）、文件產生器（`xu doc`）以及自繪 GUI 安裝精靈全部內建，零第三方相依。

### 2. 硬核技術橫向對比

| 核心維度 | C / C++ | Go | Rust | **Xu** |
| :--- | :--- | :--- | :--- | :--- |
| **記憶體管理機制** | 手動 malloc/free<br>*(易洩漏與懸空指標)* | 執行期 GC<br>*(STW 停頓與記憶體膨脹)* | 編譯期所有權<br>*(需顯式 `'a` 生命週期標註)* | **編譯期所有權<br>（零 GC / 確定性釋放）** |
| **執行期開銷** | 零成本抽象 | 較重（GC 引擎 + 排程器執行期） | 零成本抽象 | **零成本（無 GC 引擎 / 純原生機器碼）** |
| **認知心智負擔** | 易遇 UB 與競態條件 | 簡潔，但仍有 `nil` 崩潰風險 | 學習曲線陡峭（與借用檢查器搏鬥） | **極低（免生命週期標註 / 簡潔符號流）** |
| **併發模型** | 作業系統執行緒 / 外部函式庫 | CSP 協程 (`go`) + 通道 (`chan`) | 執行緒 / Async 執行期（函式染色） | **原生輕量級協程 (`xu`) + 強型別 `chan`** |
| **錯誤處理** | 錯誤碼 / 例外 *(隱式破壞控制流)* | `if err != nil` *(冗長樣板)* | `Result<T, E>` + `?` 運算子 | **符號流：`>>` 拋錯 + `or` 強制就地處理** |
| **流程控制** | `return` / `break` / `continue` | `return` / `break` / `continue` | `return` / 尾運算式 | **符號流：`<<` 回傳 / `>>` 拋錯 / `<-` 跳出** |
| **工具鏈整合度** | 分散（CMake/Make/Conan） | 開箱即用整合 | 整合（Cargo） | **單一二進位閉環（內建建置/測試/格式化/文件）** |
| **跨平台安裝** | 複雜的工具鏈與連結器相依 | 官方安裝包 / 手動設定 PATH | 依賴 rustup 與外部網路腳本 | **獨立 GUI 安裝精靈 / 一鍵安裝設定** |
| **裸機與核心開發** | 手動連結與內嵌組合語言，無安全保障 | 不支援（綁定 GC 與執行期） | 支援 (`no_std`)，但生命週期標註沉重 | **原生支援 (`freestanding` / `#core`)<br>零 GC 確定性析構 + 隱式生命週期推導** |

---

<a id="quick-start"></a>
## 🚀 零阻力快速上手 (Quick Start)

### 選項 1：瀏覽器即時沙箱（免安裝）

直接前往 **[xulang.org 線上演練場](https://xulang.org/zh-tw/playground/)**。純用戶端 WebAssembly 沙箱支援 Xu 的部分語言子集，包括基礎型別、流程控制、結構體、借用診斷與協作式通道排程。具體支援範圍請參閱演練場能力說明；真實多執行緒、網路 I/O、原生 C FFI 與桌面 UI 則需安裝原生 SDK。

### 選項 2：一行指令極速安裝（推薦）

Xu 提供內嵌編譯器與標準函式庫原始碼的獨立安裝程式，會自動註冊持久化的系統環境變數：

- **macOS / Linux**（終端機一行指令）：
  ```bash
  # 自動偵測架構、下載並完成環境設定
  curl -fsSL https://xulang.org/install.sh | bash
  ```
  *或從 [Releases](https://github.com/xulang-org/xu/releases) 下載獨立安裝程式執行：*
  ```bash
  chmod +x xu-setup-linux-x64 && ./xu-setup-linux-x64 -y
  ```

- **Windows**（GUI 精靈或 PowerShell）：
  - **GUI 安裝精靈**：從 [Releases](https://github.com/xulang-org/xu/releases) 下載 `xu-setup-windows-x64.exe`，雙擊即可執行零相依自繪安裝精靈。
  - **ARM64 主控台安裝器**：從 [Releases](https://github.com/xulang-org/xu/releases) 下載 `xu-setup-windows-arm64.exe`，於 PowerShell 執行 `.\xu-setup-windows-arm64.exe --yes`。
  - SDK 安裝器預設以目前使用者權限執行，可於一般終端機直接啟動；若需為所有使用者安裝，仍需系統管理員權限。
  - **PowerShell 一行指令**：
    ```powershell
    irm https://xulang.org/install.ps1 | iex
    ```

> 開啟新的終端機並輸入 `xu --version`，即可在任何目錄使用。

### 選項 3：30 秒執行 Hello World

```bash
# 1. 建立原始碼檔案
cat << 'EOF' > main.xu
@main

fn main() int {
    println("Hello, World! Welcome to Xu.")
    << 0
}
EOF

# 2. 立即執行
xu run main.xu

# 3. 預先靜態編譯為最佳化的原生二進位執行檔
xu build main.xu -o myapp
./myapp
```

### 官方文件

- [快速入門](https://xulang.org/zh-tw/docs/start/)
- [CLI 命令參考](https://xulang.org/zh-tw/docs/cli/)，包含最佳化、測試與 XACP
- [標準函式庫與擴充套件 API](https://xulang.org/zh/api/)
- [原生模組與借用 span](https://xulang.org/zh-tw/docs/native/)

文件與 API 原始碼統一維護於 [xulang-org/xulang-org](https://github.com/xulang-org/xulang-org)。

---

## Phone 行動應用

Xu 0.12.4 起支援產生面向 ARM64 iOS 實機、iOS 模擬器與 Android 的行動應用專案。

```sh
xu build app/ --phone --target ios-simulator-arm64 --bundle-id org.example.app -o build/ios
xu build app/ --phone --target android-arm64 --bundle-id org.example.app -o build/android
```

每個輸出目錄均包含平台建置腳本與已編譯的 Xu 原生應用目標檔。`#ui/phone` 設計層提供觸控目標、底部導覽列、自適應版面骨架、卡片、分組清單與底部彈出工作表。UI 設定檔會於本機系統 WebView Canvas 中繪製 Draw 影格，並支援透過系統輸入法（IME）輸入文字。
前置條件與邊界說明請參閱 [Phone 使用與邊界說明](src/ui/host/phone/README.md) 與 [行動端設計畫廊範例](examples/phone_gallery/README.md)。

---

## 🖥️ 裸機作業系統與核心開發 (Baremetal OS & Kernel Development)

Xu 原生支援**作業系統核心、嵌入式韌體與裸機驅動程式開發**。透過嚴格隔離的分層架構，Xu 在常規程式碼中維持**零 GC 確定性析構**與**隱式所有權推導（無需手寫生命週期標註）**，並將底層硬體操作精確隔離在最底層 5% 的程式碼中：

* **Freestanding 無宿主模式**：
  * 支援原始碼指令 `$freestanding`、專案清單 `xu.xun`（`profile: freestanding`）或 CLI 參數 `--profile=freestanding` / `--no-std`，徹底切斷對宿主作業系統系統呼叫、執行期排程器與 libc 的相依。
* **嚴格隔離的硬體控制契約**：
  * **裸指標（`*raw T`）**：解參考必須置於顯式 `unsafe { ... }` 區塊中；所有權與借用推導完全略過裸指標，確保一般應用程式碼維持零阻力體驗；
  * **Volatile MMIO 屏障**：內建 `volatile_read` 與 `volatile_write` 原語，嚴格防止無效程式碼消除（DCE）與迴圈不變量外提（LICM）；
  * **精確記憶體排布控制**：`@repr("C", align: 4096)` 用於 4KB 對齊分頁目錄表（PML4 / Page Directory），`@repr("C", packed)` 用於零填充的硬體網路封包與控制描述符。
* **純靜態核心子系統函式庫（`#core`）**：
  * `#core/arch`：CPU 特權指令（`cli`、`sti`、`hlt`、`pause`、`wfi`）、控制暫存器存取（`read_cr2/cr3`、`write_cr3`、`invlpg`、`set_vbar`、`set_trap_vector`）、IDT 中斷閘描述符（`load_idt`）、8259A PIC 重映射（`pic_remap`）與 8254 PIT 計時器初始化；
  * `#core/sync`：中斷安全自旋鎖 `IrqSpinlock` 與 `Spinlock`，搭配 RAII 守衛 `IrqGuard` 與 `SpinGuard`，在離開作用域時達成**零 GC 確定性解鎖與中斷狀態還原**；
  * `#core/task`：跨架構 192 位元組 16 位元組對齊的 `TaskContext`、原子上下文切換（`switch_context`）、完整暫存器異常快照結構（`TrapFrame`）與系統呼叫分派入口（`syscall_entry`）；
  * `#core/virtio`：純靜態 VirtIO MMIO 驅動框架、VirtQueue 描述符環、`VirtioBlkDriver`（磁碟區塊裝置）與 `VirtioNetDriver`（虛擬網路卡）；
  * `#core/mem` 與 `#core/alloc`：零配置記憶體原語（`memset`/`memcpy`/`memcmp`）與可插拔全域配置器契約（`GlobalAlloc`）。
* **一鍵建立核心專案鷹架**：
  ```bash
  # 初始化全新的裸機核心專案（自動產生 xu.xun、main.xu、linker.ld 與跨架構 Makefile）
  xu init --baremetal my_os
  cd my_os

  # 建置跨架構精簡裸機核心 ELF 映像檔（映像大小約 1.9 KB ~ 2.4 KB）
  make
  # 或直接於 QEMU 模擬器中執行
  make qemu
  ```

---

## 🗺️ 專案路線圖 (Roadmap)

本路線圖以已發布的官方 SDK 為基準。各目標平台的執行期邊界請見 [現況與限制](https://xulang.org/zh-tw/docs/status/)。

- [x] **純 Xu 自舉與原生 AOT**：以已發布的 Xu SDK 作為種子完成自舉固定點驗證，直接輸出原生機器碼與 WebAssembly
- [x] **編譯期所有權與借用推導**：確定性資源清理；0.9.4 補齊巢狀運算式與迴圈回邊的借用檢查
- [x] **原生協程與通道**：`xu` 關鍵字排程搭配強型別 `chan` 通訊；完成 100/100 多任務併發 select 門禁驗證
- [x] **密碼學套件完整性**：SM2/SM3/SM4/SM9 全套合規通過；SM9 雙線性配對堆疊框縮減 71.5% 且零編譯警告
- [x] **符號化流程與錯誤處理**：`<<` 回傳、`>>` 拋錯，以及強制就地處理的 `>>> (err) { ... }` 守衛
- [x] **多平台程式碼產生**：Windows / macOS / Linux、ARM64 / x64 / LoongArch64 / RISC-V、WASM 與裸機目標
- [x] **作業系統核心與裸機支援**：Freestanding 編譯設定檔、`#core` 純靜態子系統（arch/mem/sync/task/alloc/virtio）、中斷安全自旋鎖、原子上下文切換、VirtIO 驅動框架與一鍵專案鷹架（`xu init --baremetal`）
- [x] **SDK 安裝與自我更新**：Windows 安裝精靈、macOS PKG、跨平台單檔 Setup 與 `xu up/update`
- [x] **可重現模組相依管理**：`init/get/install`、MVS、鎖定檔/vendor、代理、離線/凍結構建與信任金鑰校驗用戶端
- [x] **LSP 與編輯器整合**：`xu-lsp` 與 VS Code/Cursor 擴充功能；支援診斷、自動補全、跳轉定義、懸停提示、符號大綱、參考查詢、重新命名與格式化
- [x] **泛型與 SSA 最佳化基礎**：解除四型別參數上限的泛型單態化、純量 SSA 提升、ARM64 SSA 迴圈核心與迴圈旋轉
- [x] **編譯器診斷與驗證**：逐階段 MIR 驗證、MIR 傾印、模式命中計數器與具名模式開關
- [x] **基礎設施生態套件**：獨立 packages 模組提供 29 個擴充套件，涵蓋 MySQL、Postgres、Redis、ClickHouse、Kafka 與 SQLite
- [x] **可追溯的跨語言基準測試**：涵蓋六個 ARM64/x86-64 平台的 72 項工作負載，保留實測編譯器版本、來源與輸出驗證
- [x] **整合式互動原始碼除錯器**：`xu debug` 透過 LLDB/GDB 驅動 DWARF 原始碼中斷點、呼叫堆疊與強型別區域變數檢視，並支援非互動批次模式
- [x] **最佳化器深度擴展**：具結構體記錄准入證明的深層 SSA 純量提升、啟發自 TVM 的 Tile 切塊規劃、低位元 LUT-GEMM 與管線化算子融合
- [ ] **完整目標機執行期驗證**：原生 SDK 安裝門禁已涵蓋 macOS ARM64/x64、Linux ARM64/x64 與 Windows x64/ARM64；持續擴展各目標的函式庫、網路、併發與桌面執行期檢查；LoongArch64 與 RISC-V SDK 採交叉編譯建置。
- [ ] **公開套件基礎設施**：信任金鑰校驗、MVS 與代理/vendor 用戶端皆已實作；公開代理/校驗服務與獨立見證仍需另行部署並驗證可用性。

---

## 🌟 加入社群並支持 Xu

Xu 是一門開源且面向未來的系統程式語言。如果你認同 **零 GC 的極致效能與優雅現代語法的結合**，誠摯邀請你加入我們！

- ⭐ **給予 Star 支持**：如果 Xu 與你的工程理念共鳴，請在 [GitHub](https://github.com/xulang-org/xu) 上點一顆 **Star**，這將是推動我們持續前進的最大動力！
- 💬 **意見回饋與討論**：有功能建議或發現問題？歡迎在 [GitHub Issues](https://github.com/xulang-org/xu/issues) 開啟討論或回報工單。
- 📊 **基準效能洞察**：在 [xulang.org/zh-tw/benchmarks](https://xulang.org/zh-tw/benchmarks/) 探索跨 72 項工作負載的深度 CPU 與記憶體基準數據。
- 📚 **完整說明文件**：於 [xulang.org](https://xulang.org/zh-tw/) 閱讀指南、語法規範與教學。

---

## 授權條款

Xu 程式語言依據 [MIT 授權條款](LICENSE) 開源釋出。
