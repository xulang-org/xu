<p align="center">
  <a href="https://xulang.org/de/"><img src="brand/xu_classic.svg" alt="Xu Logo" width="100" height="100"></a>
</p>

<h1 align="center">Die Programmiersprache Xu</h1>

<p align="center">
  <b>Go-ähnliche Nebenläufigkeit trifft auf Zero-GC-Leistung von C/Rust</b><br>
  <sub>Eine zur Kompilierzeit speichersichere Systemsprache für hohen Durchsatz, niedrige Latenz und moderne Anwendungen.</sub>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ja.md">日本語</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <b>Deutsch</b> | <a href="README.ru.md">Русский</a> | <a href="README.pt-BR.md">Português</a>
</p>

<p align="center">
  <a href="https://github.com/xulang-org/xu/releases"><img src="https://img.shields.io/github/v/release/xulang-org/xu?label=Release&color=0284c7" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-emerald.svg" alt="License"></a>
  <a href="https://xulang.org/de/"><img src="https://img.shields.io/badge/Docs-xulang.org-rose" alt="Docs"></a>
  <a href="https://xulang.org/de/benchmarks/"><img src="https://img.shields.io/badge/Benchmarks-72%20Workloads-amber" alt="Benchmarks"></a>
  <a href="https://github.com/xulang-org/xu/actions/workflows/sdk.yml"><img src="https://github.com/xulang-org/xu/actions/workflows/sdk.yml/badge.svg" alt="SDK CI"></a>
</p>

<p align="center">
  <a href="https://xulang.org/de/playground/">🌐 <b>Online-Playground (Ohne Installation)</b></a> &nbsp;•&nbsp;
  <a href="https://xulang.org/de/benchmarks/">⚡ <b>Benchmark-Dashboard (72 Workloads)</b></a> &nbsp;•&nbsp;
  <a href="#quick-start">🚀 <b>30s Schnellstart</b></a> &nbsp;•&nbsp;
  <a href="RELEASES.md">📋 <b>Versionshinweise</b></a> &nbsp;•&nbsp;
  <a href="https://github.com/xulang-org/xu/releases">📦 <b>Installer herunterladen</b></a>
</p>

---

> **Offizielle SDK-Downloads**: [GitHub Releases](https://github.com/xulang-org/xu/releases) — Vollständiges Änderungsprotokoll, inkompatible Änderungen und Migrationshinweise finden Sie in den [Versionshinweisen (RELEASES.md)](RELEASES.md).

## ⚡ Xu auf einen Blick (Zeigen statt Reden)

Kein komplexer Boilerplate. Keine umständliche Lebensdauer-Annotationsakrobatik. Erleben Sie die klare, moderne Syntax von Xu in 15 Zeilen Code:

```xu
@main
#errors

// Symbolischer Kontrollfluss: `<<` liefert zurück, `>>` wirft Fehler; kein verschachteltes Result/unwrap
fn fetch_metric(task string) int {
    if task.len == 0 { >> errors.new("empty task name") }
    << task.len * 42
}

fn worker(task string, ch chan int) {
    val := fetch_metric(task) >>> (err) { << } // Verpflichtende sichere lokale Behandlung ohne `if err != nil`
    ch <- val                                 // Typsicherer Nachrichtenaustausch über Kanäle
}

fn main() int {
    ch := chan int{cap: 2}
    xu worker("latency", ch) // Natives Schlüsselwort `xu` startet leichtgewichtige Koroutine
    xu worker("memory", ch)
    println(<-ch + <-ch)     // Fan-in-Aggregation über Kanäle
    << 0                     // Deterministische Freigabe, null GC-Pausen, statischer AOT-Native-Build
}
```

> **Warum Entwickler Xu schätzen**:
> 1. **Symbolischer Kontrollfluss**: `<<` gibt zurück, `>>` meldet Fehler, `<<<` beendet. Schluss mit ausschweifenden Alt-Schlüsselwörtern.
> 2. **Ergonomischer Fehlerfluss**: Direkt am Aufrufort über `>>> (err) { ... }` behandelt (oder mit `>>>` weitergegeben). Beseitigt endloses `if err != nil` und fatale `unwrap()`-Laufzeitabstürze.
> 3. **Native leichtgewichtige Nebenläufigkeit**: `xu worker()`-Koroutinen + `chan`-Kanäle bieten mühelose Go-ähnliche Nebenläufigkeit.
> 4. **Statische Sicherheit zur Kompilierzeit**: Verfolgt über Ownership- und Borrow-Inferenz. **Kein Garbage Collector (Zero-GC)**, keine Pausen und extrem schlanker, deterministischer Speicherverbrauch.

Ein schreibbarer Referenzname `r: $&T` erfüllt eine `&T`-Erwartung: Schreiben Sie `read(r)` oder `let view: &T = r`. Die geteilte Sicht friert den Eigentümer bis zur letzten Verwendung gegenüber kollidierenden Schreibzugriffen und Moves ein – einschließlich gespeicherter Sichten und Aufrufergebnisse. Kollidierende geteilte und schreibbare Argumente in einem Aufruf werden abgelehnt. Implizites Downgrading erfordert derzeit einen lokalen Referenznamen und denselben direkten Zieltyp. Deklarieren Sie eine veränderliche Bindung einmalig mit `$x := value` (oder `let $x: T = value`) und verwenden Sie danach schlicht `x`. Gewöhnliche Werte benötigen `&x` für einen geteilten Borrow oder `$&x` für einen schreibbaren Borrow (Referenztyp `$&T`). Verwenden Sie Referenznamen als `r` weiter oder schreiben Sie `&*r` für ein explizites Reborrow. Automatisches Borrowing von gewöhnlichen Werten ist nicht implementiert.
Hardwarenahe & Bare-Metal-Verträge: Betriebssystemkernel und Gerätetreiber arbeiten mit Rohzeigern `*raw T`, deren Dereferenzierung explizite `unsafe { ... }`-Blöcke erfordert (z. B. `p := addr as *raw u32; unsafe { *p = val }`) und von der Borrow-Inferenz vollständig umgangen wird; MMIO nutzt eingebaute `volatile_read`-/ `volatile_write`-Barrieren; Struct-Layouts unterstützen `@repr("C", align: N)` für Ausrichtung und `@repr("C", packed)` ohne Padding; Bare-Metal-Quellen setzen `$freestanding`, um Host-Syscalls und libc vollständig zu trennen.

Die aktuellen Regeln finden Sie im [Leitfaden zu Borrowing und Speichermodell](https://xulang.org/de/docs/lang/memory/).

---

## 🎯 Schmerzpunkte & „Warum Xu?“

Bei der Entwicklung hochleistungsfähiger Systeme und Dienste müssen Softwareentwickler ständig unbefriedigende Kompromisse eingehen:

### 1. Die Dilemmata, die wir lösen

- **Schmerzpunkt 1: Latenzspitzen durch Garbage Collection & aufgeblähter Speicher**
  - *Status quo*: Go und Java sind produktiv, aber GC-Stopps (STW) und unvorhersehbarer Latenz-Jitter sind in Low-Latency-Gateways, Trading-Engines und eingebetteten Zielen inakzeptabel.
  - *Die Xu-Lösung*: **Zero-GC-Laufzeit**. Reine AOT-Kompilierung. Ownership verfolgt Speicher zur Kompilierzeit und gibt ihn am Scope-Ende deterministisch frei. Keine Pausen, keine GC-Spitzen.
- **Schmerzpunkt 2: Der Kampf mit der „Hölle expliziter Lifetime-Annotationen“**
  - *Status quo*: C/C++ öffnet Tür und Tor für Dangling Pointers, Speicherkorruption und UAF-Fehler. Rust ist sicher, doch explizite Lebensdauerparameter (`'a`, `'b`) und komplexe Typ-Akrobatik bremsen die Entwicklung spürbar aus.
  - *Die Xu-Lösung*: **Implizite Ownership-Inferenz & Borrow-Prüfung**. Keine expliziten Lifetime-Annotationen im Anwendungscode. Natürliche Wertsemantik für Slices vereint Sicherheit und Geschwindigkeit.
- **Schmerzpunkt 3: Bildschirmfüllender Boilerplate & verschachtelte Fehler-Wrapper**
  - *Status quo*: Go-Codebasen sind voller repetitivem `if err != nil`. Rust verpackt Typen in mehrere `Result<T, E>`-/`Option`-Schichten.
  - *Die Xu-Lösung*: **Symbolisches `>>` kombiniert mit verpflichtendem `>>> (err) { ... }`** für schlanke, klare und sichere Fehlerweitergabe.
- **Schmerzpunkt 4: Fragmentierte Toolchains & Einrichtungsaufwand**
  - *Status quo*: Das Zusammensetzen von CMake, Make, Paketmanagern und plattformspezifischen Linkern ist bekanntermaßen fehleranfällig.
  - *Die Xu-Lösung*: **Geschlossener Einzel-Binary-Kreislauf**. Alles – Compiler, Test-Runner, Formatierer (`xu fmt`), Dokumentationsgenerator (`xu doc`) und selbst gerenderte GUI-Setup-Assistenten – ist direkt integriert.

### 2. Technischer Direktvergleich

| Schlüsseldimension | C / C++ | Go | Rust | **Xu** |
| :--- | :--- | :--- | :--- | :--- |
| **Speicherverwaltung** | Manuelles `malloc`/`free`<br>*(Lecks & Dangling Pointers)* | Laufzeit-GC<br>*(STW-Pausen & Speicherwachstum)* | Compile-Time-Ownership<br>*(Explizite `'a`-Annotationen)* | **Compile-Time-Ownership<br>(Zero-GC / Deterministische Freigabe)** |
| **Laufzeit-Overhead** | Zero-Cost-Abstraktionen | Hoch (GC-Engine + Scheduler) | Zero-Cost-Abstraktionen | **Zero-Cost (Keine GC-Engine / Reiner nativer Maschinencode)** |
| **Kognitive Last** | Anfällig für UB & Race Conditions | Einfach, aber `nil`-Panics bleiben | Steile Lernkurve (Borrow-Checker-Kämpfe) | **Minimal (Keine Lifetime-Annotationen / Klarer Symbolfluss)** |
| **Nebenläufigkeit** | OS-Threads / Externe Bibliotheken | CSP-Koroutinen (`go`) + Kanäle (`chan`) | Threads / Async-Runtimes (Funktionsfärbung) | **Native leichtgewichtige Koroutinen (`xu`) + typisierte `chan`** |
| **Fehlerbehandlung** | Fehlercodes / Exceptions *(Implizit)* | `if err != nil` *(Langer Boilerplate)* | `Result<T, E>` + `?`-Operator | **Symbolfluss: `>>` werfen + verpflichtendes `or`** |
| **Kontrollfluss** | `return` / `break` / `continue` | `return` / `break` / `continue` | `return` / Endausdrücke | **Symbolfluss: `<<` zurück / `>>` Fehler / `<-` Abbruch** |
| **Toolchain-Kohäsion** | Fragmentiert (CMake/Make/Conan) | Out-of-the-box integriert | Integriert (Cargo) | **Einzel-Binary-Kreislauf (Build/Test/Fmt/Doc integriert)** |
| **Plattformübergreifendes Setup** | Komplexe Toolchain- & Linker-Abhängigkeiten | Offizieller Installer / manuelles PATH | Benötigt rustup & externe Netzskripte | **Eigenständige GUI-Assistenten / Ein-Klick-Setup** |
| **Bare-Metal & Kernel-Entwicklung** | Manuelles Linken & Inline-Asm, unsicher | Nicht unterstützt (GC & Runtime) | Unterstützt (`no_std`), aber schwere Lifetimes | **Native Unterstützung (`freestanding` / `#core`)<br>Zero-GC deterministisches Drop + Inferierte Lifetimes** |

---

<a id="quick-start"></a>
## 🚀 Reibungsloser Schnellstart

### Option 1: Sofortige Browser-Sandbox (Keine Installation)

Starten Sie direkt im **[xulang.org Online-Playground](https://xulang.org/de/playground/)**. Die clientseitige WebAssembly-Sandbox unterstützt eine Teilmenge von Xu einschließlich Basistypen, Kontrollfluss, Structs, Borrow-Diagnosen und kooperativer Kanal-Planung. Details zum Umfang finden Sie im Funktionsleitfaden des Playgrounds; echtes Multithreading, Netzwerk-I/O, native C-FFI und Desktop-UI erfordern das native SDK.

### Option 2: Einzeiler-Schnellinstallation (Empfohlen)

Xu bietet eigenständige Installer mit eingebettetem Compiler und Standardbibliothek-Quellen, die dauerhafte Systemumgebungsvariablen automatisch registrieren:

- **macOS / Linux** (Ein Befehl im Terminal):
  ```bash
  # Erkennt Architektur, lädt herunter und richtet die Umgebung automatisch ein
  curl -fsSL https://xulang.org/install.sh | bash
  ```
  *Oder eigenständige Binärdateien aus [Releases](https://github.com/xulang-org/xu/releases) herunterladen:*
  ```bash
  chmod +x xu-setup-linux-x64 && ./xu-setup-linux-x64 -y
  ```

- **Windows** (GUI-Assistent oder PowerShell):
  - **GUI-Assistent**: Laden Sie `xu-setup-windows-x64.exe` aus [Releases](https://github.com/xulang-org/xu/releases) herunter und starten Sie per Doppelklick den abhängigkeitsfreien, selbst gerenderten Assistenten.
  - **ARM64-Konsolen-Installer**: Laden Sie `xu-setup-windows-arm64.exe` aus [Releases](https://github.com/xulang-org/xu/releases) herunter und führen Sie `.\xu-setup-windows-arm64.exe --yes` in PowerShell aus.
  - SDK-Installer sind für die Ausführung im aktuellen Benutzerkontext ausgelegt und starten aus einem normalen Terminal. Die Installation für alle Benutzer erfordert weiterhin Administratorrechte.
  - **PowerShell-Einzeiler**:
    ```powershell
    irm https://xulang.org/install.ps1 | iex
    ```

> Öffnen Sie ein neues Terminal und geben Sie `xu --version` ein, um Xu überall auszuführen.

### Option 3: 30-Sekunden Hello World

```bash
# 1. Quelldatei erstellen
cat << 'EOF' > main.xu
@main

fn main() int {
    println("Hello, World! Welcome to Xu.")
    << 0
}
EOF

# 2. Sofort ausführen
xu run main.xu

# 3. Ahead-of-time zu einem optimierten nativen Binary kompilieren
xu build main.xu -o myapp
./myapp
```

### Dokumentation

- [Erste Schritte](https://xulang.org/de/docs/start/)
- [CLI-Referenz](https://xulang.org/de/docs/cli/), einschließlich Optimierung, Tests und XACP
- [API der Standardbibliothek und Pakete](https://xulang.org/api/)
- [Native Module und geliehene Spans](https://xulang.org/de/docs/native/)

Dokumentation und API-Quellen befinden sich in [xulang-org/xulang-org](https://github.com/xulang-org/xulang-org).

---

## Mobile (Phone) Anwendungen

Xu 0.12.4 generiert ARM64-Anwendungsprojekte für iOS-Geräte, den iOS-Simulator und Android.

```sh
xu build app/ --phone --target ios-simulator-arm64 --bundle-id org.example.app -o build/ios
xu build app/ --phone --target android-arm64 --bundle-id org.example.app -o build/android
```

Jede Ausgabe enthält ein Plattform-Build-Skript und ein kompiliertes Xu-Anwendungsobjekt. Die Designschicht `#ui/phone` umfasst Touch-Ziele, untere Navigation, adaptive Scaffolds, Karten, gruppierte Zeilen und Bottom Sheets. Das UI-Profil rendert Draw-Frames in einem lokalen System-WebView-Canvas und unterstützt Texteingabe über das System-IME.
Siehe [Phone-Voraussetzungen und Grenzen](src/ui/host/phone/README.md) sowie die [mobile Design-Galerie](examples/phone_gallery/README.md).

---

## 🖥️ Bare-Metal-OS- & Kernel-Entwicklung

Xu unterstützt nativ **Betriebssystemkernel, eingebettete Firmware und Bare-Metal-Treiber**. Durch eine strikt isolierte Schichtenarchitektur bewahrt Xu **deterministische Zero-GC-Freigabe** und **implizite Ownership-Inferenz (ohne manuelle Lifetime-Annotationen)** im regulären Code, während hardwarenahe Eingriffe sauber in die untersten 5 % des Codes isoliert werden:

* **Freestanding-Modus ohne Host**:
  * Die Quell-Direktive `$freestanding`, das Projektmanifest `xu.xun` (`profile: freestanding`) oder die CLI-Flags `--profile=freestanding` / `--no-std` trennen Abhängigkeiten zu Host-OS-Syscalls, Runtime-Schedulern und libc vollständig ab.
* **Strikt isolierte Hardware-Verträge**:
  * **Rohzeiger (`*raw T`)**: Dereferenzierung erfordert explizite `unsafe { ... }`-Blöcke; Ownership- und Borrow-Inferenz überspringen Rohzeiger vollständig, sodass regulärer Anwendungscode reibungsfrei bleibt;
  * **Volatile-MMIO-Barrieren**: Eingebaute Primitive `volatile_read` und `volatile_write` verhindern Dead-Code-Elimination (DCE) und Loop-Invariant Code Motion (LICM);
  * **Präzise Speicherlayout-Steuerung**: `@repr("C", align: 4096)` für 4-KB-ausgerichtete Seitentabellen (PML4 / Page Directory) und `@repr("C", packed)` für Hardware-Netzwerkpakete und Steuerdeskriptoren ohne Padding.
* **Rein statische Kern-Subsystembibliothek (`#core`)**:
  * `#core/arch`: Privilegierte CPU-Instruktionen (`cli`, `sti`, `hlt`, `pause`, `wfi`), Zugriff auf Steuerregister (`read_cr2/cr3`, `write_cr3`, `invlpg`, `set_vbar`, `set_trap_vector`), IDT-Interrupt-Gate-Deskriptoren (`load_idt`), 8259A-PIC-Remapping (`pic_remap`) und 8254-PIT-Timer-Initialisierung;
  * `#core/sync`: Interrupt-sichere Spinlocks `IrqSpinlock` und `Spinlock` gepaart mit RAII-Guards `IrqGuard` und `SpinGuard` für **deterministische Zero-GC-Freigabe und Interrupt-Wiederherstellung am Scope-Ende**;
  * `#core/task`: Architekturübergreifender 192-Byte-, 16-Byte-ausgerichteter `TaskContext`, atomarer Kontextwechsel (`switch_context`), vollständige Register-Trap-Snapshots (`TrapFrame`) und Syscall-Dispatch-Einstiege (`syscall_entry`);
  * `#core/virtio`: Rein statisches VirtIO-MMIO-Treiberframework, VirtQueue-Deskriptorringe, `VirtioBlkDriver` (Festplatten-Blockgerät) und `VirtioNetDriver` (virtuelle Netzwerkkarte);
  * `#core/mem` & `#core/alloc`: Allokationsfreie Speicher-Intrinsics (`memset`/`memcpy`/`memcmp`) und austauschbare Allokator-Verträge (`GlobalAlloc`).
* **Sofortiges Kernel-Projektgerüst**:
  ```bash
  # Neues Bare-Metal-Kernel-Projekt initialisieren (erstellt xu.xun, main.xu, linker.ld und Multi-Arch-Makefile)
  xu init --baremetal my_os
  cd my_os

  # Schlanke Bare-Metal-Kernel-ELF-Images plattformübergreifend bauen (~1,9 KB bis 2,4 KB Imagegröße)
  make
  # Oder direkt im QEMU-Emulator starten
  make qemu
  ```

---

## 🗺️ Projekt-Roadmap

Das veröffentlichte SDK bildet die Grundlage dieser Roadmap. Zielspezifische Laufzeitgrenzen siehe [Status & Einschränkungen](https://xulang.org/de/docs/status/).

- [x] **Reines Xu Self-Hosting und natives AOT**: Bootstrap aus einem veröffentlichten Xu SDK, Fixpunkt-Verifikation und direkte Ausgabe von nativem Maschinencode und WebAssembly
- [x] **Compile-Time-Ownership und Borrow-Inferenz**: Deterministische Ressourcenbereinigung; 0.9.4 vervollständigt Prüfungen für verschachtelte Ausdrücke und Schleifen-Rückkanten
- [x] **Native Koroutinen & Kanäle**: Planung über das Schlüsselwort `xu` gepaart mit typisierter `chan`-Kommunikation; 100/100 Multitask-`select`-Nebenläufigkeitsgate bestanden
- [x] **Vollständigkeit der Kryptografie-Suite**: Vollständige SM2/SM3/SM4/SM9-Konformität; SM9-Pairing-Stackframe um 71,5 % reduziert bei null Compilerwarnungen
- [x] **Symbolischer Fluss & Fehlerbehandlung**: `<<` Rückgabe, `>>` Fehlerwurf und verpflichtende lokale `>>> (err) { ... }`-Guards
- [x] **Multi-Plattform-Codegenerierung**: Windows / macOS / Linux, ARM64 / x64 / LoongArch64 / RISC-V, WASM und Bare-Metal-Ziele
- [x] **Betriebssystemkernel- & Bare-Metal-Unterstützung**: Freestanding-Kompilierprofil, rein statisches Subsystem `#core` (arch/mem/sync/task/alloc/virtio), interrupt-sichere Spinlocks, atomarer Kontextwechsel, VirtIO-Treiberframework und Ein-Befehl-Gerüst (`xu init --baremetal`)
- [x] **SDK-Installation und Selbst-Updates**: Windows-Assistent, macOS-PKG, plattformübergreifendes Einzeldatei-Setup und `xu up/update`
- [x] **Reproduzierbare Modulabhängigkeiten**: `init/get/install`, MVS, Lockfiles/Vendor, Proxies, Offline-/Frozen-Builds und Checksum-Client mit vertrauenswürdigem Schlüssel
- [x] **LSP- & Editor-Integration**: `xu-lsp` und VS-Code-/Cursor-Erweiterungen; Diagnosen, Vervollständigung, Definitionen, Hover, Symbole, Referenzen, Umbenennen und Formatierung
- [x] **Generics & SSA-Optimierungsgrundlagen**: Monomorphisierung ohne die Grenze von vier Typparametern, skalare SSA-Promotion, ARM64-SSA-Schleifenkerne und Schleifenrotation
- [x] **Compiler-Diagnosen und Verifikation**: MIR-Prüfung pro Pass, MIR-Dumps, Muster-Trefferzähler und benannte Mustersteuerungen
- [x] **Infrastruktur-Pakete**: Das separate packages-Modul bietet 29 Erweiterungen darunter MySQL, Postgres, Redis, ClickHouse, Kafka und SQLite
- [x] **Nachvollziehbare sprachübergreifende Benchmarks**: 72 Workloads auf sechs ARM64/x86-64-Plattformen mit gemessenen Compilerversionen, Herkunft und Ausgabeverifikation
- [x] **Integrierter interaktiver Quellcode-Debugger**: `xu debug` steuert DWARF-Quell-Breakpoints, Aufrufstapel und typisierte lokale Variableninspektion über LLDB/GDB samt nicht-interaktivem Batch-Modus
- [x] **Weitere Optimierer-Erweiterung**: Tiefere skalare SSA-Promotion mit Struct-Record-Zulassungsbeweisen, TVM-inspirierte Tile-Planung, Low-Bit-LUT-GEMM und gepipelinete Operatorfusion
- [ ] **Vollständige Zielmaschinen-Laufzeitvalidierung**: Native SDK-Installationsgates decken macOS ARM64/x64, Linux ARM64/x64 und Windows x64/ARM64 ab. Laufzeitprüfungen für Bibliotheken, Netzwerk, Nebenläufigkeit und Desktop-UI auf jedem Ziel werden weiter ausgebaut; LoongArch64- und RISC-V-SDKs werden cross-kompiliert.
- [ ] **Öffentliche Paket-Infrastruktur**: Prüfsummenverifikation mit vertrauenswürdigem Schlüssel, MVS und Proxy-/Vendor-Clients sind implementiert. Öffentliche Proxy-/Checksum-Dienste und unabhängige Zeugen erfordern separate Bereitstellung und Verfügbarkeitsprüfung.

---

## 🌟 Der Community beitreten & Xu unterstützen

Xu ist eine offene, zukunftsorientierte Systemprogrammiersprache. Wenn Sie an **extreme Zero-GC-Leistung kombiniert mit ergonomischer moderner Syntax** glauben, laden wir Sie herzlich ein!

- ⭐ **Dem Repo einen Stern geben**: Wenn Xu Ihrer Ingenieursphilosophie entspricht, geben Sie uns einen **Star** auf [GitHub](https://github.com/xulang-org/xu) – das treibt unsere Entwicklung voran!
- 💬 **Feedback & Diskussionen**: Haben Sie Funktionswünsche oder Vorschläge? Eröffnen Sie eine Diskussion oder ein Ticket in den [GitHub Issues](https://github.com/xulang-org/xu/issues).
- 📊 **Benchmark-Einblicke**: Entdecken Sie tiefgehende CPU- und Speicher-Benchmarks über 72 Workloads unter [xulang.org/de/benchmarks](https://xulang.org/de/benchmarks/).
- 📚 **Umfassende Dokumentation**: Lesen Sie Leitfäden, Syntaxspezifikationen und Tutorials auf [xulang.org](https://xulang.org/de/).

---

## Lizenz

Die Programmiersprache Xu ist Open Source unter der [MIT-Lizenz](LICENSE).
