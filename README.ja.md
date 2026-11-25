<p align="center">
  <a href="https://xulang.org/ja/"><img src="brand/xu_classic.svg" alt="Xu Logo" width="100" height="100"></a>
</p>

<h1 align="center">Xu プログラミング言語</h1>

<p align="center">
  <b>Go のような直感的な並行処理と C/Rust 級のゼロ GC パフォーマンスを両立</b><br>
  <sub>高スループット・低レイテンシ・モダンなアプリケーションのために設計された、コンパイル時メモリ安全なシステム言語。</sub>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <b>日本語</b> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a> | <a href="README.ru.md">Русский</a> | <a href="README.pt-BR.md">Português</a>
</p>

<p align="center">
  <a href="https://github.com/xulang-org/xu/releases"><img src="https://img.shields.io/github/v/release/xulang-org/xu?label=Release&color=0284c7" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-emerald.svg" alt="License"></a>
  <a href="https://xulang.org/ja/"><img src="https://img.shields.io/badge/Docs-xulang.org-rose" alt="Docs"></a>
  <a href="https://xulang.org/ja/benchmarks/"><img src="https://img.shields.io/badge/Benchmarks-72%20Workloads-amber" alt="Benchmarks"></a>
  <a href="https://github.com/xulang-org/xu/actions/workflows/sdk.yml"><img src="https://github.com/xulang-org/xu/actions/workflows/sdk.yml/badge.svg" alt="SDK CI"></a>
</p>

<p align="center">
  <a href="https://xulang.org/ja/playground/">🌐 <b>オンラインプレイグラウンド（インストール不要）</b></a> &nbsp;•&nbsp;
  <a href="https://xulang.org/ja/benchmarks/">⚡ <b>72 ワークロード・ベンチマーク</b></a> &nbsp;•&nbsp;
  <a href="#quick-start">🚀 <b>30 秒クイックスタート</b></a> &nbsp;•&nbsp;
  <a href="RELEASES.md">📋 <b>リリースノート</b></a> &nbsp;•&nbsp;
  <a href="https://github.com/xulang-org/xu/releases">📦 <b>インストーラーをダウンロード</b></a>
</p>

---

> **公式 SDK ダウンロード**：[GitHub Releases](https://github.com/xulang-org/xu/releases) — 詳細な変更履歴、破壊的変更、移行ガイドについては [リリースノート (RELEASES.md)](RELEASES.md) をご覧ください。

## ⚡ 一目でわかる Xu（Show, Don't Tell）

複雑なボイラープレートも、煩雑なライフタイム注釈の体操も不要です。わずか 15 行のコードで Xu のクリーンでモダンな構文を体感してください：

```xu
@main
#errors

// シンボルによる制御フロー：<< で返却、>> でエラー送出；Result/unwrap のネストを排除
fn fetch_metric(task string) int {
    if task.len == 0 { >> errors.new("empty task name") }
    << task.len * 42
}

fn worker(task string, ch chan int) {
    val := fetch_metric(task) or (err) { << } // if err != nil なしで安全なローカル処理を強制
    ch <- val                                 // 型安全なチャネルによるメッセージ送信
}

fn main() int {
    ch := chan int{cap: 2}
    xu worker("latency", ch) // ネイティブの xu キーワードで軽量コルーチンを起動
    xu worker("memory", ch)
    println(<-ch + <-ch)     // チャネルからのファンイン集約
    << 0                     // 決定論的解放、ゼロ GC 停止、静的 AOT ネイティブビルド
}
```

> **開発者に選ばれる理由**：
> 1. **シンボルベースの制御フロー**：`<<` で return、`>>` でエラー送出、`<<<` で終了。冗長な従来キーワードに別れを告げます。
> 2. **快適なエラーフロー**：呼び出し側で `or (err) { ... }` により処理。画面を埋め尽くす `if err != nil` や実行時の致命的な `unwrap()` パニックを排除します。
> 3. **ネイティブ軽量並行処理**：`xu worker()` コルーチンと `chan` チャネルで、Go のように直感的な並行プログラミングを実現します。
> 4. **コンパイル時の静的安全性**：所有権と借用推論により追跡。**ガベージコレクタ不要（Zero-GC）**、停止時間ゼロ、極めてスリムで決定論的なメモリ消費を実現します。

書き込み可能参照名 `r: $&T` は `&T` を要求する箇所に渡せます：`read(r)` または `let view: &T = r` と記述できます。共有ビューは、保存されたビューや呼び出し結果を含め最後の使用まで親の競合する書き込みやムーブを凍結します。1 つの呼び出し内で競合する共有引数と書き込み可能引数は拒否されます。暗黙のダウングレードは現在、ローカル参照名かつ同一の直接参照先型を要求します。可変バインディングは宣言時に 1 回だけ `$x := value`（または `let $x: T = value`）と記し、以降は通常の `x` を使います。通常の値から共有借用を得るには `&x`、書き込み可能借用には `$&x`（参照型は `$&T`）を使います。参照名の再利用はそのまま `r`、明示的な再借用は `&*r` と書きます。通常の値からの自動借用は未実装です。
低レベルハードウェアおよびベアメタル契約：OS カーネルやデバイスドライバは生ポインタ `*raw T` を用いて操作し、デリファレンスには明示的な `unsafe { ... }` ブロックが必要です（例：`p := addr as *raw u32; unsafe { *p = val }`）。生ポインタは借用推論から完全にバイパスされます。MMIO には組み込みの `volatile_read` / `volatile_write` バリアを使用し、構造体レイアウトには `@repr("C", align: N)` アライメントおよび `@repr("C", packed)` パディングなし指定が利用可能です。ベアメタルソースでは `$freestanding` を指定することでホストのシステムコールと libc への依存を完全に断ち切ります。

最新のルールについては [借用とメモリモデルガイド](https://xulang.org/ja/docs/lang/memory/) をご覧ください。

---

## 🎯 課題と「なぜ Xu なのか？」

高性能なシステムやサービスを構築するエンジニアは、常に不完全なトレードオフの選択を迫られています：

### 1. Xu が解決するジレンマ

- **課題 1：ガベージコレクションによるレイテンシスパイクとメモリ肥大化**
  - *現状*：Go や Java は生産性が高い一方で、GC 停止（STW）と予測不能なレイテンシジッタは、低遅延ゲートウェイ、トレーディングエンジン、組み込みターゲットでは致命的です。
  - *Xu の解決策*：**ゼロ GC ランタイム**。純粋な AOT コンパイルとコンパイル時所有権管理により、スコープ終了時にメモリを決定論的に解放します。停止ゼロ、GC スパイクゼロ。
- **課題 2：「明示的ライフタイム注釈地獄」との戦い**
  - *現状*：C/C++ はダングリングポインタ、メモリ破壊、UAF バグの危険を伴います。Rust は安全ですが、明示的ライフタイムパラメータ（`'a`, `'b`）と複雑な型パズルが開発速度を大きく低下させます。
  - *Xu の解決策*：**暗黙的所有権推論と借用チェック**。アプリケーションコードに明示的なライフタイム注釈は不要です。スライスの自然な値セマンティクスにより、安全性と開発速度を両立します。
- **課題 3：画面を埋めるボイラープレートと多層エラーラッパー**
  - *現状*：Go コードベースは反復的な `if err != nil` で溢れ、Rust は `Result<T, E>` / `Option` の多層ラップを要求します。
  - *Xu の解決策*：**シンボル `>>` と必須の `or (err) { ... }` の組み合わせ**により、軽量で簡潔かつ安全なエラー伝播を提供します。
- **課題 4：分断されたツールチェーンとセットアップの手間**
  - *現状*：CMake、Make、パッケージマネージャ、各プラットフォームのリンカを繋ぎ合わせる作業は脆弱で煩雑です。
  - *Xu の解決策*：**単一バイナリの完結ループ**。コンパイラ、テストランナー、フォーマッタ（`xu fmt`）、ドキュメント生成器（`xu doc`）、独自描画の GUI セットアップウィザードまですべて内蔵されています。

### 2. ハードコア技術比較

| 主要観点 | C / C++ | Go | Rust | **Xu** |
| :--- | :--- | :--- | :--- | :--- |
| **メモリ管理** | 手動 malloc/free<br>*(リーク・ダングリングポインタ)* | ランタイム GC<br>*(STW 停止・メモリ肥大化)* | コンパイル時所有権<br>*(明示的 `'a` ライフタイム注釈)* | **コンパイル時所有権<br>（ゼロ GC / 決定論的解放）** |
| **ランタイム負荷** | ゼロコスト抽象化 | 重い（GC エンジン＋スケジューラ） | ゼロコスト抽象化 | **ゼロコスト（GC なし / 純粋なネイティブ機械語）** |
| **認知負荷** | UB・データ競合に脆弱 | シンプルだが `nil` パニックが残存 | 学習曲線が急（借用チェッカとの格闘） | **最小限（ライフタイム注釈不要 / 明快なシンボル制御）** |
| **並行モデル** | OS スレッド / 外部ライブラリ | CSP コルーチン (`go`) + チャネル (`chan`) | スレッド / Async ランタイム（関数カラーリング） | **ネイティブ軽量コルーチン (`xu`) + 型付き `chan`** |
| **エラー処理** | エラーコード / 例外 *(暗黙的)* | `if err != nil` *(冗長なボイラープレート)* | `Result<T, E>` + `?` 演算子 | **シンボル流：`>>` 送出 + `or` 強制処理** |
| **制御フロー** | `return` / `break` / `continue` | `return` / `break` / `continue` | `return` / 末尾式 | **シンボル流：`<<` 返却 / `>>` 送出 / `<-` 脱出** |
| **ツールチェーン統合** | 分散（CMake/Make/Conan） | 標準で統合 | 統合（Cargo） | **単一バイナリ完結（ビルド/テスト/整形/文書生成を内蔵）** |
| **クロスプラットフォーム導入** | 複雑なツールチェーン・リンカ依存 | 公式インストーラ / 手動 PATH 設定 | rustup と外部ネットワークスクリプトが必要 | **独立 GUI セットアップウィザード / ワンクリック導入** |
| **ベアメタル・カーネル開発** | 手動リンク・インライン asm、非安全 | 非対応（GC・ランタイム依存） | 対応 (`no_std`) だがライフタイム記述が重い | **ネイティブ対応 (`freestanding` / `#core`)<br>ゼロ GC 決定論的破棄 + 暗黙的ライフタイム推論** |

---

<a id="quick-start"></a>
## 🚀 ゼロ摩擦クイックスタート

### オプション 1：ブラウザ即時サンドボックス（インストール不要）

**[xulang.org オンラインプレイグラウンド](https://xulang.org/ja/playground/)** をすぐに開いてお試しください。クライアントサイド WebAssembly サンドボックスは、基本型、制御フロー、構造体、借用診断、協調的チャネルスケジューリングを含む Xu のサブセットをサポートしています。対応範囲の詳細はプレイグラウンドの機能ガイドをご覧ください。本格的なマルチスレッド、ネットワーク I/O、ネイティブ C FFI、デスクトップ UI にはネイティブ SDK が必要です。

### オプション 2：ワンライナー高速インストール（推奨）

Xu はコンパイラと標準ライブラリソースを同梱したスタンドアロンインストーラを提供しており、永続的なシステム環境変数を自動的に登録します：

- **macOS / Linux**（ターミナルで 1 行コマンド）：
  ```bash
  # アーキテクチャを自動検出し、ダウンロードと環境設定を実施
  curl -fsSL https://xulang.org/install.sh | bash
  ```
  *または [Releases](https://github.com/xulang-org/xu/releases) からスタンドアロンバイナリをダウンロードして実行：*
  ```bash
  chmod +x xu-setup-linux-x64 && ./xu-setup-linux-x64 -y
  ```

- **Windows**（GUI ウィザードまたは PowerShell）：
  - **GUI ウィザード**：[Releases](https://github.com/xulang-org/xu/releases) から `xu-setup-windows-x64.exe` をダウンロードし、ダブルクリックで依存ゼロの独自描画ウィザードを起動します。
  - **ARM64 コンソールインストーラ**：[Releases](https://github.com/xulang-org/xu/releases) から `xu-setup-windows-arm64.exe` をダウンロードし、PowerShell で `.\xu-setup-windows-arm64.exe --yes` を実行します。
  - SDK インストーラは現在ユーザー権限での実行を宣言しているため、通常のターミナルから起動可能です。全ユーザー向けにインストールする場合は引き続き管理者権限が必要です。
  - **PowerShell ワンライナー**：
    ```powershell
    irm https://xulang.org/install.ps1 | iex
    ```

> 新しいターミナルを開いて `xu --version` と入力すれば、どこからでも実行できます。

### オプション 3：30 秒 Hello World

```bash
# 1. ソースファイルを作成
cat << 'EOF' > main.xu
@main

fn main() int {
    println("Hello, World! Welcome to Xu.")
    << 0
}
EOF

# 2. 即座に実行
xu run main.xu

# 3. 最適化されたネイティブバイナリへ AOT コンパイル
xu build main.xu -o myapp
./myapp
```

### ドキュメント

- [入門ガイド](https://xulang.org/ja/docs/start/)
- [CLI リファレンス](https://xulang.org/ja/docs/cli/)（最適化、テスト、XACP を含む）
- [標準ライブラリ・拡張パッケージ API](https://xulang.org/api/)
- [ネイティブモジュールと借用スパン](https://xulang.org/ja/docs/native/)

ドキュメントおよび API のソースは [xulang-org/xulang-org](https://github.com/xulang-org/xulang-org) で管理されています。

---

## モバイル（Phone）アプリケーション

Xu 0.12.4 より、ARM64 iOS 実機、iOS シミュレータ、および Android 向けのアプリケーションプロジェクト生成に対応しています。

```sh
xu build app/ --phone --target ios-simulator-arm64 --bundle-id org.example.app -o build/ios
xu build app/ --phone --target android-arm64 --bundle-id org.example.app -o build/android
```

各出力ディレクトリには、プラットフォーム向けビルドスクリプトとコンパイル済み Xu アプリケーションオブジェクトが含まれます。`#ui/phone` デザインレイヤーは、タッチターゲット、ボトムナビゲーション、アダプティブスキャフォールド、カード、グループ化行、ボトムシートを提供します。UI プロファイルはローカルシステム WebView の Canvas 上に Draw フレームを描画し、システム IME を介したテキスト入力に対応します。
前提条件と境界については [Phone の前提条件と境界](src/ui/host/phone/README.md) および [モバイルデザインギャラリー](examples/phone_gallery/README.md) を参照してください。

---

## 🖥️ ベアメタル OS・カーネル開発

Xu は **オペレーティングシステムカーネル、組み込みファームウェア、ベアメタルデバイスドライバ開発** をネイティブにサポートします。厳密に分離されたレイヤー設計により、通常コードでは **ゼロ GC の決定論的破棄** と **暗黙的所有権推論（手動ライフタイム注釈不要）** を保ちながら、ハードウェア直結の操作を最下層 5% のコードに隔離できます：

* **Freestanding 非ホストモード**：
  * ソースディレクティブ `$freestanding`、プロジェクトマニフェスト `xu.xun`（`profile: freestanding`）、または CLI フラグ `--profile=freestanding` / `--no-std` により、ホスト OS のシステムコール、ランタイムスケジューラ、libc への依存を完全に遮断します。
* **厳密に隔離されたハードウェア契約**：
  * **生ポインタ（`*raw T`）**：デリファレンスには明示的な `unsafe { ... }` ブロックが必要であり、所有権・借用推論は生ポインタを完全にバイパスするため、通常のアプリケーションコードに摩擦を与えません；
  * **Volatile MMIO バリア**：組み込みの `volatile_read` および `volatile_write` プリミティブが、デッドコード削除（DCE）やループ不変式移動（LICM）を防止します；
  * **精密なメモリレイアウト制御**：4KB ページディレクトリテーブル（PML4 / Page Directory）向けの `@repr("C", align: 4096)` と、パディングなしのハードウェアネットワークパケットや制御記述子向けの `@repr("C", packed)` を提供します。
* **純粋静的コアサブシステムライブラリ（`#core`）**：
  * `#core/arch`：CPU 特権命令（`cli`, `sti`, `hlt`, `pause`, `wfi`）、制御レジスタアクセス（`read_cr2/cr3`, `write_cr3`, `invlpg`, `set_vbar`, `set_trap_vector`）、IDT 割り込みゲート記述子（`load_idt`）、8259A PIC 再マッピング（`pic_remap`）、8254 PIT タイマ初期化；
  * `#core/sync`：割り込み安全なスピンロック `IrqSpinlock` および `Spinlock` と RAII ガード `IrqGuard` / `SpinGuard` により、スコープ終了時に **ゼロ GC で決定論的にロック解放と割り込み復元** を実行；
  * `#core/task`：クロスアーキテクチャ 192 バイト・16 バイトアライメントの `TaskContext`、アトミックなコンテキストスイッチ（`switch_context`）、全レジスタ例外スナップショット構造体（`TrapFrame`）、システムコールディスパッチエントリ（`syscall_entry`）；
  * `#core/virtio`：純粋静的 VirtIO MMIO ドライバフレームワーク、VirtQueue 記述子リング、`VirtioBlkDriver`（ディスクブロックデバイス）、`VirtioNetDriver`（仮想ネットワークカード）；
  * `#core/mem` & `#core/alloc`：ゼロアロケーションのメモリ組み込み関数（`memset`/`memcpy`/`memcmp`）と差し替え可能なアロケータ契約（`GlobalAlloc`）。
* **カーネルプロジェクトの即時スキャフォールド**：
  ```bash
  # 新規ベアメタルカーネルプロジェクトを初期化（xu.xun、main.xu、linker.ld、マルチアーキテクチャ Makefile を自動生成）
  xu init --baremetal my_os
  cd my_os

  # 各アーキテクチャ向けの軽量ベアメタルカーネル ELF バイナリをビルド（約 1.9 KB〜2.4 KB）
  make
  # または QEMU エミュレータ上で直接実行
  make qemu
  ```

---

## 🗺️ プロジェクトロードマップ

公開済み SDK を基準としたロードマップです。ターゲット別のランタイム境界については [ステータスと制限](https://xulang.org/ja/docs/status/) をご参照ください。

- [x] **純粋 Xu セルフホスティングとネイティブ AOT**：公開済み Xu SDK からブートストラップし、不動点を検証した上でネイティブ機械語と WebAssembly を直接出力
- [x] **コンパイル時所有権と借用推論**：決定論的リソース解放；0.9.4 でネスト式とループバックエッジの借用検査を完了
- [x] **ネイティブコルーチンとチャネル**：`xu` キーワードによるスケジューリングと型付き `chan` 通信；100/100 マルチタスク並行 select ゲートを完了
- [x] **暗号スイートの完全性**：SM2/SM3/SM4/SM9 フルスイート適合試験に合格；SM9 ペアリングのスタックフレームを 71.5% 削減しコンパイル警告ゼロを達成
- [x] **シンボル制御フローとエラー処理**：`<<` 返却、`>>` 送出、必須のローカル `or (err) { ... }` ガード
- [x] **マルチプラットフォームコード生成**：Windows / macOS / Linux、ARM64 / x64 / LoongArch64 / RISC-V、WASM、ベアメタルターゲット
- [x] **OS カーネル・ベアメタル対応**：Freestanding コンパイルプロファイル、`#core` 純粋静的サブシステム（arch/mem/sync/task/alloc/virtio）、割り込み安全スピンロック、アトミックコンテキストスイッチ、VirtIO ドライバフレームワーク、ワンコマンドスキャフォールド（`xu init --baremetal`）
- [x] **SDK インストールと自己アップデート**：Windows ウィザード、macOS PKG、クロスプラットフォーム単一ファイル Setup、`xu up/update`
- [x] **再現可能なモジュール依存関係**：`init/get/install`、MVS、ロックファイル/vendor、プロキシ、オフライン/フローズンビルド、信頼鍵チェックサムクライアント
- [x] **LSP とエディタ統合**：`xu-lsp` および VS Code/Cursor 拡張；診断、補完、定義ジャンプ、ホバー、シンボル、参照検索、リネーム、フォーマット
- [x] **ジェネリクスと SSA 最適化基盤**：4 型パラメータ上限を撤廃した単相化、スカラー SSA 昇格、ARM64 SSA ループカーネル、ループ回転
- [x] **コンパイラ診断と検証**：パス毎の MIR 検証、MIR ダンプ、パターンヒットカウンタ、名前付きパターン制御
- [x] **インフラストラクチャパッケージ**：独立 packages モジュールにて MySQL、Postgres、Redis、ClickHouse、Kafka、SQLite を含む 29 の拡張パッケージを提供
- [x] **追跡可能なクロス言語ベンチマーク**：6 つの ARM64/x86-64 プラットフォームで 72 ワークロードを計測し、実測コンパイラバージョン・出所・出力検証結果を保持
- [x] **統合インタラクティブソースデバッガ**：`xu debug` が LLDB/GDB 経由で DWARF ソースブレークポイント、コールスタック、型付きローカル変数検査を駆動（非対話バッチモード対応）
- [x] **最適化器のさらなる拡張**：構造体レコード受入証明を伴う深い SSA スカラー昇格、TVM 着想のタイル計画、低ビット LUT-GEMM、パイプライン化された演算子融合
- [ ] **ターゲット実機での完全なランタイム検証**：ネイティブ SDK インストールゲートは macOS ARM64/x64、Linux ARM64/x64、Windows x64/ARM64 をカバー。各ターゲットでのライブラリ、ネットワーク、並行処理、デスクトップランタイム検査をさらに拡充中。LoongArch64 および RISC-V SDK はクロスビルドで提供。
- [ ] **パブリックパッケージインフラ**：信頼鍵チェックサム検証、MVS、プロキシ/vendor クライアントは実装済み。公開プロキシ/チェックサムサービスおよび独立ウィットネスは別途デプロイと可用性検証が必要。

---

## 🌟 コミュニティへの参加と Xu の応援

Xu はオープンソースで未来志向のシステムプログラミング言語です。**ゼロ GC の極限パフォーマンスと人間工学に基づいたモダンな構文の両立** に共感される方は、ぜひご参加ください！

- ⭐ **リポジトリに Star を付ける**：Xu のエンジニアリング哲学に共感いただけたら、[GitHub](https://github.com/xulang-org/xu) で **Star** をお願いします。開発の大きな原動力になります！
- 💬 **フィードバックとディスカッション**：機能要望や提案があれば、[GitHub Issues](https://github.com/xulang-org/xu/issues) でお気軽にディスカッションやチケットを作成してください。
- 📊 **ベンチマークの詳細**：72 ワークロードにわたる CPU・メモリ性能の徹底比較は [xulang.org/ja/benchmarks](https://xulang.org/ja/benchmarks/) で確認できます。
- 📚 **包括的なドキュメント**：ガイド、構文仕様、チュートリアルは [xulang.org](https://xulang.org/ja/) をご覧ください。

---

## ライセンス

Xu プログラミング言語は [MIT ライセンス](LICENSE) の下でオープンソースとして公開されています。
