<p align="center">
  <a href="https://xulang.org/ko/"><img src="brand/xu_classic.svg" alt="Xu Logo" width="100" height="100"></a>
</p>

<h1 align="center">Xu 프로그래밍 언어</h1>

<p align="center">
  <b>Go 수준의 직관적인 동시성과 C/Rust 급 제로 GC 성능의 만남</b><br>
  <sub>높은 처리량, 낮은 지연 시간, 그리고 현대적인 애플리케이션을 위해 설계된 컴파일 타임 메모리 안전 시스템 언어.</sub>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ja.md">日本語</a> | <b>한국어</b> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a> | <a href="README.ru.md">Русский</a> | <a href="README.pt-BR.md">Português</a>
</p>

<p align="center">
  <a href="https://github.com/xulang-org/xu/releases"><img src="https://img.shields.io/github/v/release/xulang-org/xu?label=Release&color=0284c7" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-emerald.svg" alt="License"></a>
  <a href="https://xulang.org/ko/"><img src="https://img.shields.io/badge/Docs-xulang.org-rose" alt="Docs"></a>
  <a href="https://xulang.org/ko/benchmarks/"><img src="https://img.shields.io/badge/Benchmarks-72%20Workloads-amber" alt="Benchmarks"></a>
  <a href="https://github.com/xulang-org/xu/actions/workflows/sdk.yml"><img src="https://github.com/xulang-org/xu/actions/workflows/sdk.yml/badge.svg" alt="SDK CI"></a>
</p>

<p align="center">
  <a href="https://xulang.org/ko/playground/">🌐 <b>온라인 플레이그라운드 (무설치)</b></a> &nbsp;•&nbsp;
  <a href="https://xulang.org/ko/benchmarks/">⚡ <b>72개 워크로드 벤치마크 대시보드</b></a> &nbsp;•&nbsp;
  <a href="#quick-start">🚀 <b>30초 빠른 시작</b></a> &nbsp;•&nbsp;
  <a href="RELEASES.md">📋 <b>릴리스 노트</b></a> &nbsp;•&nbsp;
  <a href="https://github.com/xulang-org/xu/releases">📦 <b>설치 파일 다운로드</b></a>
</p>

---

> **공식 SDK 다운로드**: [GitHub Releases](https://github.com/xulang-org/xu/releases) — 전체 변경 이력, 호환성 변경 및 마이그레이션 가이드는 [릴리스 노트 (RELEASES.md)](RELEASES.md)를 참고하세요.

## ⚡ 한눈에 보는 Xu (Show, Don't Tell)

복잡한 보일러플레이트도, 난해한 수명 주기(lifetime) 주석 체조도 없습니다. 단 15줄의 코드로 Xu의 깔끔한 현대적 문법을 직접 확인해 보세요:

```xu
@main
#errors

// 기호 기반 제어 흐름: `<<` 반환, `>>` 오류 송출; 중첩된 Result/unwrap 보일러플레이트 제거
fn fetch_metric(task string) int {
    if task.len == 0 { >> errors.new("empty task name") }
    << task.len * 42
}

fn worker(task string, ch chan int) {
    val := fetch_metric(task) >>> (err) { << } // `if err != nil` 없이 안전한 로컬 처리를 강제
    ch <- val                                 // 타입 안전 채널 메시지 전달
}

fn main() int {
    ch := chan int{cap: 2}
    xu worker("latency", ch) // 네이티브 `xu` 키워드로 경량 코루틴 실행
    xu worker("memory", ch)
    println(<-ch + <-ch)     // 채널 팬인(fan-in) 집계
    << 0                     // 결정론적 해제, GC 멈춤 없음, 정적 AOT 네이티브 빌드
}
```

> **개발자들이 Xu를 사랑하는 이유**:
> 1. **기호 기반 제어 흐름**: `<<` 반환, `>>` 오류 발생, `<<<` 종료. 장황한 기존 키워드를 걷어냈습니다.
> 2. **인체공학적인 오류 흐름**: 호출 지점에서 `>>> (err) { ... }`로 처리하거나 `>>>`로 전파합니다. 화면을 채우는 `if err != nil`과 치명적인 런타임 `unwrap()` 패닉을 원천 제거합니다.
> 3. **네이티브 경량 동시성**: `xu worker()` 코루틴과 `chan` 채널로 Go처럼 간편한 동시성 프로그래밍을 제공합니다.
> 4. **컴파일 타임 정적 안전성**: 소유권 및 대여 추론으로 메모리를 추적합니다. **가비지 컬렉터 없음(Zero-GC)**, 지연 멈춤 없음, 극도로 간결하고 결정론적인 메모리 사용량을 보장합니다.

쓰기 가능한 참조 이름 `r: $&T`는 `&T`가 기대되는 자리에 그대로 전달할 수 있습니다: `read(r)` 또는 `let view: &T = r`처럼 작성하세요. 공유 뷰는 저장된 뷰와 호출 반환값을 포함해 마지막 사용 시점까지 부모의 충돌하는 쓰기와 이동을 동결합니다. 단일 호출에서 충돌하는 공유 인자와 쓰기 가능 인자는 거부됩니다. 암시적 다운그레이드는 현재 로컬 참조 이름과 동일한 직접 대상 타입을 요구합니다. 가변 바인딩은 선언 시 한 번만 `$x := value`(또는 `let $x: T = value`)로 표기하고 이후에는 일반 `x`를 사용합니다. 일반 값에서 공유 대여를 얻으려면 `&x`, 쓰기 가능 대여는 `$&x`(참조 타입 `$&T`)를 사용합니다. 참조 이름을 재사용할 때는 `r`, 명시적 재대여는 `&*r`로 작성합니다. 일반 값에 대한 자동 대여는 구현되어 있지 않습니다.
저수준 하드웨어 및 베어메탈 계약: OS 커널과 디바이스 드라이버는 원시 포인터 `*raw T`로 동작하며, 역참조에는 명시적 `unsafe { ... }` 블록이 필요합니다(예: `p := addr as *raw u32; unsafe { *p = val }`). 원시 포인터는 대여 추론에서 완전히 제외됩니다. MMIO는 내장 `volatile_read` / `volatile_write` 배리어를 사용하며, 구조체 레이아웃은 `@repr("C", align: N)` 정렬과 `@repr("C", packed)` 패딩 제거를 지원합니다. 베어메탈 소스는 `$freestanding`을 선언해 호스트 시스템 콜 및 libc 의존성을 완전히 차단합니다.

최신 규칙은 [대여 및 메모리 모델 가이드](https://xulang.org/ko/docs/lang/memory/)를 참조하세요.

---

## 🎯 해결하는 문제와 "왜 Xu인가?"

고성능 시스템과 서비스를 구축하는 엔지니어들은 늘 불완전한 트레이드오프 사이에서 선택을 강요받습니다:

### 1. Xu가 해결하는 핵심 딜레마

- **문제 1: 가비지 컬렉션(GC) 지연 스파이크와 메모리 비대화**
  - *현황*: Go와 Java는 생산성이 높지만, GC 멈춤(STW)과 예측 불가능한 지연 지터는 저지연 게이트웨이, 트레이딩 엔진, 임베디드 환경에서 치명적인 약점입니다.
  - *Xu의 해법*: **제로 GC 런타임**. 순수 AOT 컴파일과 컴파일 타임 소유권 추적으로 스코프 종료 시 메모리를 결정론적으로 즉시 해제합니다. 멈춤도, GC 스파이크도 없습니다.
- **문제 2: "명시적 수명 주기 주석 지옥"과의 싸움**
  - *현황*: C/C++은 댕글링 포인터, 메모리 손상, UAF 취약점에 노출되어 있습니다. Rust는 안전하지만 명시적 라이프타임 매개변수(`'a`, `'b`)와 복잡한 타입 체조가 개발 속도를 크게 떨어뜨립니다.
  - *Xu의 해법*: **암시적 소유권 추론 및 대여 검사**. 애플리케이션 코드에 명시적 수명 주기 주석이 필요 없으며, 슬라이스의 자연스러운 값 의미론으로 안전성과 개발 속도를 모두 잡았습니다.
- **문제 3: 화면을 뒤덮는 보일러플레이트와 중첩된 오류 래퍼**
  - *현황*: Go 코드베이스는 반복적인 `if err != nil`로 가득하고, Rust는 여러 겹의 `Result<T, E>` / `Option` 래핑이 필요합니다.
  - *Xu의 해법*: **기호 `>>`와 필수 `>>> (err) { ... }`의 결합**으로 가볍고 깔끔하며 안전한 오류 전파를 제공합니다.
- **문제 4: 파편화된 도구 체인과 번거로운 설치**
  - *현황*: CMake, Make, 패키지 매니저, 플랫폼별 링커를 조합하는 과정은 깨지기 쉽고 복잡합니다.
  - *Xu의 해법*: **단일 바이너리 완결 구조**. 컴파일러, 테스트 러너, 포매터(`xu fmt`), 문서 생성기(`xu doc`), 자체 렌더링 GUI 설치 마법사까지 모두 내장되어 있습니다.

### 2. 핵심 기술 비교

| 주요 비교 항목 | C / C++ | Go | Rust | **Xu** |
| :--- | :--- | :--- | :--- | :--- |
| **메모리 관리** | 수동 malloc/free<br>*(누수 및 댕글링 포인터)* | 런타임 GC<br>*(STW 멈춤 및 메모리 비대화)* | 컴파일 타임 소유권<br>*(명시적 `'a` 수명 주석)* | **컴파일 타임 소유권<br>(Zero-GC / 결정론적 해제)** |
| **런타임 오버헤드** | 제로 비용 추상화 | 무거움 (GC 엔진 + 스케줄러 런타임) | 제로 비용 추상화 | **제로 비용 (GC 엔진 없음 / 순수 네이티브 기계어)** |
| **인지적 부담** | UB 및 경쟁 조건에 취약 | 단순하지만 `nil` 패닉 상존 | 가파른 학습 곡선 (대여 검사기와의 씨름) | **최소화 (수명 주석 없음 / 깔끔한 기호 제어 흐름)** |
| **동시성 모델** | OS 스레드 / 외부 라이브러리 | CSP 코루틴 (`go`) + 채널 (`chan`) | 스레드 / Async 런타임 (함수 컬러링) | **네이티브 경량 코루틴 (`xu`) + 타입 안전 `chan`** |
| **오류 처리** | 오류 코드 / 예외 *(암묵적)* | `if err != nil` *(과도한 보일러플레이트)* | `Result<T, E>` + `?` 연산자 | **기호 흐름: `>>` 송출 + `or` 필수 로컬 처리** |
| **제어 흐름** | `return` / `break` / `continue` | `return` / `break` / `continue` | `return` / 꼬리 표현식 | **기호 흐름: `<<` 반환 / `>>` 오류 / `<-` 탈출** |
| **도구 체인 통합도** | 파편화 (CMake/Make/Conan) | 기본 통합 제공 | 통합 (Cargo) | **단일 바이너리 완결 (빌드/테스트/포맷/문서 내장)** |
| **크로스 플랫폼 설치** | 복잡한 도구 체인 및 링커 의존 | 공식 설치기 / 수동 PATH 설정 | rustup 및 외부 네트워크 스크립트 필요 | **독립 실행 GUI 설치 마법사 / 원클릭 설치** |
| **베어메탈·커널 개발** | 수동 링크 및 인라인 asm, 비안전 | 미지원 (GC 및 런타임 종속) | 지원 (`no_std`), 단 무거운 수명 주석 | **네이티브 지원 (`freestanding` / `#core`)<br>제로 GC 결정론적 소멸 + 암시적 수명 추론** |

---

<a id="quick-start"></a>
## 🚀 마찰 없는 빠른 시작 (Quick Start)

### 옵션 1: 브라우저 즉시 샌드박스 (무설치)

**[xulang.org 온라인 플레이그라운드](https://xulang.org/ko/playground/)** 로 바로 이동해 보세요. 클라이언트 사이드 WebAssembly 샌드박스는 기본 타입, 제어 흐름, 구조체, 대여 진단, 협력적 채널 스케줄링을 포함한 Xu의 핵심 부분집합을 지원합니다. 지원 범위는 플레이그라운드 기능 가이드를 참고하세요. 실제 멀티스레딩, 네트워크 I/O, 네이티브 C FFI, 데스크톱 UI에는 네이티브 SDK가 필요합니다.

### 옵션 2: 한 줄 명령으로 빠른 설치 (권장)

Xu는 컴파일러와 표준 라이브러리 소스가 내장된 독립 설치 프로그램을 제공하며, 영구 시스템 환경 변수를 자동으로 등록합니다:

- **macOS / Linux** (터미널 한 줄 명령):
  ```bash
  # 아키텍처 자동 감지, 다운로드 및 환경 자동 설정
  curl -fsSL https://xulang.org/install.sh | bash
  ```
  *또는 [Releases](https://github.com/xulang-org/xu/releases)에서 독립 바이너리를 다운로드하여 실행:*
  ```bash
  chmod +x xu-setup-linux-x64 && ./xu-setup-linux-x64 -y
  ```

- **Windows** (GUI 마법사 또는 PowerShell):
  - **GUI 마법사**: [Releases](https://github.com/xulang-org/xu/releases)에서 `xu-setup-windows-x64.exe`를 다운로드하고 더블 클릭하여 의존성 없는 자체 렌더링 마법사를 실행하세요.
  - **ARM64 콘솔 설치기**: [Releases](https://github.com/xulang-org/xu/releases)에서 `xu-setup-windows-arm64.exe`를 다운로드한 뒤 PowerShell에서 `.\xu-setup-windows-arm64.exe --yes`를 실행하세요.
  - SDK 설치 프로그램은 현재 사용자 권한 실행을 선언하므로 일반 터미널에서 시작할 수 있습니다. 모든 사용자용 설치에는 관리자 권한이 필요합니다.
  - **PowerShell 한 줄 명령**:
    ```powershell
    irm https://xulang.org/install.ps1 | iex
    ```

> 새 터미널을 열고 `xu --version`을 입력하면 어디서나 바로 실행할 수 있습니다.

### 옵션 3: 30초 Hello World

```bash
# 1. 소스 파일 생성
cat << 'EOF' > main.xu
@main

fn main() int {
    println("Hello, World! Welcome to Xu.")
    << 0
}
EOF

# 2. 즉시 실행
xu run main.xu

# 3. 최적화된 네이티브 바이너리로 AOT 컴파일
xu build main.xu -o myapp
./myapp
```

### 공식 문서

- [시작하기 가이드](https://xulang.org/ko/docs/start/)
- [CLI 레퍼런스](https://xulang.org/ko/docs/cli/) (최적화, 테스트, XACP 포함)
- [표준 라이브러리 및 확장 패키지 API](https://xulang.org/api/)
- [네이티브 모듈과 대여 스팬(span)](https://xulang.org/ko/docs/native/)

문서와 API 소스는 [xulang-org/xulang-org](https://github.com/xulang-org/xulang-org)에서 통합 관리됩니다.

---

## 모바일(Phone) 애플리케이션

Xu 0.12.4부터 ARM64 iOS 실기기, iOS 시뮬레이터 및 Android용 애플리케이션 프로젝트 생성을 지원합니다.

```sh
xu build app/ --phone --target ios-simulator-arm64 --bundle-id org.example.app -o build/ios
xu build app/ --phone --target android-arm64 --bundle-id org.example.app -o build/android
```

각 출력 디렉터리에는 플랫폼 빌드 스크립트와 컴파일된 Xu 애플리케이션 오브젝트가 포함됩니다. `#ui/phone` 디자인 계층은 터치 타깃, 하단 내비게이션, 적응형 스캐폴드, 카드, 그룹화 행 및 바텀 시트를 제공합니다. UI 프로파일은 로컬 시스템 WebView Canvas에서 Draw 프레임을 렌더링하며 시스템 IME를 통한 텍스트 입력을 지원합니다.
사전 요구 사항과 경계는 [Phone 사전 조건 및 지원 범위](src/ui/host/phone/README.md) 및 [모바일 디자인 갤러리](examples/phone_gallery/README.md)를 참고하세요.

---

## 🖥️ 베어메탈 OS 및 커널 개발

Xu는 **운영체제 커널, 임베디드 펌웨어, 베어메탈 드라이버 개발**을 네이티브로 지원합니다. 엄격히 분리된 계층형 아키텍처를 통해 일반 코드에서는 **제로 GC 결정론적 소멸**과 **암시적 소유권 추론(수동 수명 주석 불필요)**을 유지하면서, 하드웨어 수준 조작을 최하위 5% 코드에 안전하게 격리합니다:

* **Freestanding 비호스트 모드**:
  * 소스 지시어 `$freestanding`, 프로젝트 매니페스트 `xu.xun`(`profile: freestanding`), 또는 CLI 플래그 `--profile=freestanding` / `--no-std`를 통해 호스트 OS 시스템 콜, 런타임 스케줄러, libc 의존성을 완전히 차단합니다.
* **엄격히 격리된 하드웨어 계약**:
  * **원시 포인터(`*raw T`)**: 역참조에는 명시적 `unsafe { ... }` 블록이 필수이며, 소유권 및 대여 추론은 원시 포인터를 완전히 건너뛰어 일반 애플리케이션 코드의 마찰 없는 경험을 유지합니다;
  * **Volatile MMIO 배리어**: 내장 `volatile_read` 및 `volatile_write` 프리미티브가 죽은 코드 제거(DCE)와 루프 불변 코드 이동(LICM)을 방지합니다;
  * **정밀한 메모리 레이아웃 제어**: 4KB 페이지 디렉터리 테이블(PML4 / Page Directory)을 위한 `@repr("C", align: 4096)`과 패딩 없는 하드웨어 네트워크 패킷 및 제어 디스크립터를 위한 `@repr("C", packed)`를 지원합니다.
* **순수 정적 코어 서브시스템 라이브러리(`#core`)**:
  * `#core/arch`: CPU 특권 명령어(`cli`, `sti`, `hlt`, `pause`, `wfi`), 제어 레지스터 접근(`read_cr2/cr3`, `write_cr3`, `invlpg`, `set_vbar`, `set_trap_vector`), IDT 인터럽트 게이트 디스크립터(`load_idt`), 8259A PIC 리매핑(`pic_remap`), 8254 PIT 타이머 초기화;
  * `#core/sync`: 인터럽트 안전 스핀락 `IrqSpinlock` 및 `Spinlock`과 RAII 가드 `IrqGuard` / `SpinGuard`를 결합하여 스코프 종료 시 **제로 GC 결정론적 락 해제 및 인터럽트 복원** 보장;
  * `#core/task`: 크로스 아키텍처 192바이트 16바이트 정렬 `TaskContext`, 원자적 컨텍스트 스위칭(`switch_context`), 전체 레지스터 트랩 스냅샷 구조체(`TrapFrame`), 시스템 콜 디스패치 진입점(`syscall_entry`);
  * `#core/virtio`: 순수 정적 VirtIO MMIO 드라이버 프레임워크, VirtQueue 디스크립터 링, `VirtioBlkDriver`(디스크 블록 장치), `VirtioNetDriver`(가상 네트워크 카드);
  * `#core/mem` 및 `#core/alloc`: 제로 할당 메모리 내장 함수(`memset`/`memcpy`/`memcmp`)와 교체 가능한 전역 할당기 계약(`GlobalAlloc`).
* **즉시 생성되는 커널 프로젝트 스캐폴딩**:
  ```bash
  # 새 베어메탈 커널 프로젝트 초기화 (xu.xun, main.xu, linker.ld, 멀티 아키텍처 Makefile 자동 생성)
  xu init --baremetal my_os
  cd my_os

  # 여러 아키텍처용 경량 베어메탈 커널 ELF 바이너리 빌드 (~1.9 KB ~ 2.4 KB 크기)
  make
  # 또는 QEMU 에뮬레이터에서 바로 실행
  make qemu
  ```

---

## 🗺️ 프로젝트 로드맵

공개된 공식 SDK를 기준으로 한 로드맵입니다. 타깃별 런타임 경계는 [현황 및 제한 사항](https://xulang.org/ko/docs/status/)을 참고하세요.

- [x] **순수 Xu 셀프 호스팅 및 네이티브 AOT**: 공개된 Xu SDK로 부트스트랩하여 고정점을 검증하고 네이티브 기계어 및 WebAssembly를 직접 생성
- [x] **컴파일 타임 소유권 및 대여 추론**: 결정론적 리소스 정리; 0.9.4에서 중첩 표현식과 루프 백엣지(back-edge) 대여 검사 완료
- [x] **네이티브 코루틴과 채널**: `xu` 키워드 스케줄링과 타입 안전 `chan` 통신; 100/100 멀티태스크 동시성 select 게이트 통과
- [x] **암호화 스위트 완성도**: SM2/SM3/SM4/SM9 전 스위트 적합성 검증 통과; SM9 페어링 스택 프레임 71.5% 절감 및 컴파일 경고 0건
- [x] **기호 기반 흐름 제어 및 오류 처리**: `<<` 반환, `>>` 오류 송출, 필수 로컬 `>>> (err) { ... }` 가드
- [x] **멀티 플랫폼 코드 생성**: Windows / macOS / Linux, ARM64 / x64 / LoongArch64 / RISC-V, WASM 및 베어메탈 타깃
- [x] **운영체제 커널 및 베어메탈 지원**: Freestanding 컴파일 프로파일, `#core` 순수 정적 서브시스템(arch/mem/sync/task/alloc/virtio), 인터럽트 안전 스핀락, 원자적 컨텍스트 스위칭, VirtIO 드라이버 프레임워크 및 원커맨드 스캐폴딩(`xu init --baremetal`)
- [x] **SDK 설치 및 자가 업데이트**: Windows 마법사, macOS PKG, 크로스 플랫폼 단일 파일 Setup 및 `xu up/update`
- [x] **재현 가능한 모듈 의존성**: `init/get/install`, MVS, 락파일/vendor, 프록시, 오프라인/프로즌 빌드 및 신뢰 키 체크섬 클라이언트
- [x] **LSP 및 에디터 통합**: `xu-lsp` 및 VS Code/Cursor 확장; 진단, 자동 완성, 정의 이동, 호버, 심볼, 참조, 이름 변경 및 포매팅
- [x] **제네릭 및 SSA 최적화 기반**: 4개 타입 매개변수 상한을 제거한 단형화(monomorphization), 스칼라 SSA 승격, ARM64 SSA 루프 커널 및 루프 회전
- [x] **컴파일러 진단 및 검증**: 패스별 MIR 검증, MIR 덤프, 패턴 히트 카운터 및 명명된 패턴 제어
- [x] **인프라 생태계 패키지**: 독립 packages 모듈을 통해 MySQL, Postgres, Redis, ClickHouse, Kafka, SQLite 등 29개 확장 제공
- [x] **추적 가능한 크로스 언어 벤치마크**: 6개 ARM64/x86-64 플랫폼의 72개 워크로드, 실측 컴파일러 버전·출처·출력 검증 보존
- [x] **통합 대화형 소스 디버거**: `xu debug`가 LLDB/GDB를 통해 DWARF 소스 중단점, 호출 스택 및 타입별 지역 변수 검사 구동(비대화형 배치 모드 지원)
- [x] **최적화기 심화 확장**: 구조체 레코드 허용 증명을 갖춘 깊은 SSA 스칼라 승격, TVM 스타일 타일 플래닝, 저비트 LUT-GEMM 및 파이프라인 연산자 융합
- [ ] **완전한 타깃 머신 런타임 검증**: 네이티브 SDK 설치 게이트는 macOS ARM64/x64, Linux ARM64/x64 및 Windows x64/ARM64를 커버합니다. 각 타깃의 라이브러리, 네트워킹, 동시성 및 데스크톱 런타임 검사를 지속 확장 중이며, LoongArch64 및 RISC-V SDK는 크로스 빌드로 제공됩니다.
- [ ] **공개 패키지 인프라**: 신뢰 키 체크섬 검증, MVS 및 프록시/vendor 클라이언트가 구현되어 있습니다. 공개 프록시/체크섬 서비스와 독립 검증자(witness)는 별도 배포 및 가용성 검증이 필요합니다.

---

## 🌟 커뮤니티 참여 및 Xu 응원하기

Xu는 오픈소스이자 미래 지향적인 시스템 프로그래밍 언어입니다. **제로 GC의 극한 성능과 현대적이고 인체공학적인 문법의 조화**를 믿으신다면 함께해 주세요!

- ⭐ **저장소에 Star 누르기**: Xu의 엔지니어링 철학에 공감하셨다면 [GitHub](https://github.com/xulang-org/xu)에서 **Star**를 눌러주세요 — 개발에 큰 힘이 됩니다!
- 💬 **피드백 및 토론**: 기능 요청이나 제안이 있으신가요? [GitHub Issues](https://github.com/xulang-org/xu/issues)에서 토론이나 이슈를 열어주세요.
- 📊 **벤치마크 인사이트**: [xulang.org/ko/benchmarks](https://xulang.org/ko/benchmarks/)에서 72개 워크로드에 걸친 심층 CPU 및 메모리 벤치마크를 살펴보세요.
- 📚 **종합 문서**: 가이드, 문법 명세 및 튜토리얼은 [xulang.org](https://xulang.org/ko/)에서 확인하실 수 있습니다.

---

## 라이선스

Xu 프로그래밍 언어는 [MIT 라이선스](LICENSE)에 따라 오픈소스로 배포됩니다.
