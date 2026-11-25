<p align="center">
  <a href="https://xulang.org/pt-br/"><img src="brand/xu_classic.svg" alt="Xu Logo" width="100" height="100"></a>
</p>

<h1 align="center">A Linguagem de Programação Xu</h1>

<p align="center">
  <b>Concorrência no estilo Go unida ao desempenho Zero-GC de C/Rust</b><br>
  <sub>Uma linguagem de sistemas com segurança de memória em tempo de compilação, projetada para alto throughput, baixa latência e aplicações modernas.</sub>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ja.md">日本語</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a> | <a href="README.ru.md">Русский</a> | <b>Português</b>
</p>

<p align="center">
  <a href="https://github.com/xulang-org/xu/releases"><img src="https://img.shields.io/github/v/release/xulang-org/xu?label=Release&color=0284c7" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-emerald.svg" alt="License"></a>
  <a href="https://xulang.org/pt-br/"><img src="https://img.shields.io/badge/Docs-xulang.org-rose" alt="Docs"></a>
  <a href="https://xulang.org/pt-br/benchmarks/"><img src="https://img.shields.io/badge/Benchmarks-72%20Workloads-amber" alt="Benchmarks"></a>
  <a href="https://github.com/xulang-org/xu/actions/workflows/sdk.yml"><img src="https://github.com/xulang-org/xu/actions/workflows/sdk.yml/badge.svg" alt="SDK CI"></a>
</p>

<p align="center">
  <a href="https://xulang.org/pt-br/playground/">🌐 <b>Playground Online (Sem Instalação)</b></a> &nbsp;•&nbsp;
  <a href="https://xulang.org/pt-br/benchmarks/">⚡ <b>Painel de Benchmarks (72 Cargas)</b></a> &nbsp;•&nbsp;
  <a href="#quick-start">🚀 <b>Início Rápido em 30s</b></a> &nbsp;•&nbsp;
  <a href="RELEASES.md">📋 <b>Notas de Versão</b></a> &nbsp;•&nbsp;
  <a href="https://github.com/xulang-org/xu/releases">📦 <b>Baixar Instaladores</b></a>
</p>

---

> **Downloads oficiais do SDK**: [GitHub Releases](https://github.com/xulang-org/xu/releases) — Consulte as [Notas de Versão (RELEASES.md)](RELEASES.md) para o histórico completo, mudanças incompatíveis e detalhes de migração.

## ⚡ Xu em um Olhar (Mostre, Não Apenas Conte)

Sem código repetitivo complexo. Sem malabarismos de anotações explícitas de tempo de vida. Experimente a sintaxe limpa e moderna de Xu em 15 linhas de código:

```xu
@main
#errors

// Controle de fluxo simbólico: `<<` retorna, `>>` lança erros; sem aninhamento de Result/unwrap
fn fetch_metric(task string) int {
    if task.len == 0 { >> errors.new("empty task name") }
    << task.len * 42
}

fn worker(task string, ch chan int) {
    val := fetch_metric(task) or (err) { << } // Tratamento local seguro obrigatório sem `if err != nil`
    ch <- val                                 // Troca de mensagens em canais com segurança de tipos
}

fn main() int {
    ch := chan int{cap: 2}
    xu worker("latency", ch) // A palavra-chave nativa `xu` inicia uma corrotina leve
    xu worker("memory", ch)
    println(<-ch + <-ch)     // Agregação fan-in via canais
    << 0                     // Liberação determinística, zero pausas de GC, compilação AOT nativa estática
}
```

> **Por que os desenvolvedores adoram**:
> 1. **Controle de fluxo simbólico**: `<<` retorna, `>>` lança erro, `<<<` encerra. Adeus às palavras-chave verbosas legadas.
> 2. **Fluxo de erros ergonômico**: Tratado no ponto de chamada com `or (err) { ... }`. Elimina a poluição visual de `if err != nil` e os pânicos catastróficos de `unwrap()` em tempo de execução.
> 3. **Concorrência leve nativa**: Corrotinas `xu worker()` + canais `chan` oferecem concorrência intuitiva no estilo Go.
> 4. **Segurança estática em compilação**: Rastreada por inferência de propriedade e empréstimo. **Sem coletor de lixo (Zero-GC)**, zero pausas e consumo determinístico ultraenxuto de memória.

Um nome de referência gravável `r: $&T` pode atender a uma expectativa `&T`: escreva `read(r)` ou `let view: &T = r`. A visão compartilhada mantém o proprietário congelado contra escritas e movimentações conflitantes até o último uso, incluindo visões armazenadas e retornos de chamada. Argumentos compartilhados e graváveis conflitantes em uma mesma chamada são rejeitados. O rebaixamento implícito exige atualmente um nome de referência local e o mesmo tipo direto apontado. Declare uma variável mutável uma única vez com `$x := value` (ou `let $x: T = value`) e use apenas `x` em seguida. Valores comuns exigem `&x` para empréstimo compartilhado ou `$&x` para empréstimo gravável, cujo tipo de referência é `$&T`. Reutilize nomes de referência como `r`, ou escreva `&*r` para um reempréstimo explícito. Empréstimo automático a partir de valores comuns não é implementado.
Contratos de hardware de baixo nível e bare-metal: núcleos de sistemas operacionais e drivers de dispositivos operam com ponteiros brutos `*raw T`, cuja desreferenciação exige blocos explícitos `unsafe { ... }` (ex.: `p := addr as *raw u32; unsafe { *p = val }`), completamente ignorados pela inferência de empréstimo; MMIO usa barreiras nativas `volatile_read` / `volatile_write`; o layout de structs aceita alinhamento `@repr("C", align: N)` e empacotamento sem preenchimento `@repr("C", packed)`; arquivos bare-metal especificam `$freestanding` para cortar vínculos com syscalls do host e com a libc.

Consulte o [Guia de empréstimo e modelo de memória](https://xulang.org/pt-br/docs/lang/memory/) para as regras atuais.

---

## 🎯 Dores Reais e "Por que Xu?"

Como engenheiros de software construindo sistemas e serviços de alto desempenho, somos constantemente forçados a escolher entre concessões imperfeitas:

### 1. Os dilemas que resolvemos

- **Dor 1: Picos de latência do Garbage Collector e inchaço de memória**
  - *Situação atual*: Go e Java são produtivos, mas pausas STW do GC e variação imprevisível de latência são inviáveis em gateways de baixa latência, motores de negociação e sistemas embarcados.
  - *A solução Xu*: **Runtime Zero-GC**. Compilação AOT pura. A propriedade rastreia a memória em tempo de compilação e a libera deterministicamente ao sair do escopo. Zero pausas, zero picos de GC.
- **Dor 2: A batalha contra o "inferno de anotações explícitas de lifetime"**
  - *Situação atual*: C/C++ expõe você a ponteiros pendentes, corrupção de memória e falhas UAF. Rust é seguro, mas parâmetros explícitos de tempo de vida (`'a`, `'b`) e ginástica de tipos desaceleram drasticamente o desenvolvimento.
  - *A solução Xu*: **Inferência implícita de propriedade e verificação de empréstimos**. Nenhuma anotação explícita de lifetime no código de aplicação. Semântica natural por valor para slices entrega segurança e velocidade juntas.
- **Dor 3: Código repetitivo tomando a tela e camadas de wrappers de erro**
  - *Situação atual*: Bases de código Go ficam tomadas por `if err != nil` repetitivos. Rust envolve tipos em múltiplas camadas de `Result<T, E>` / `Option`.
  - *A solução Xu*: **Símbolo `>>` combinado com `or (err) { ... }` obrigatório**, oferecendo propagação de erros leve, limpa e segura.
- **Dor 4: Toolchains fragmentadas e atrito na instalação**
  - *Situação atual*: Costurar CMake, Make, gerenciadores de pacotes e linkers de cada plataforma é notoriamente frágil.
  - *A solução Xu*: **Ciclo fechado em binário único**. Tudo — compilador, executor de testes, formatador (`xu fmt`), gerador de documentação (`xu doc`) e assistentes gráficos GUI autorrenderizados — já vem embutido.

### 2. Comparação técnica direta

| Dimensão chave | C / C++ | Go | Rust | **Xu** |
| :--- | :--- | :--- | :--- | :--- |
| **Gestão de memória** | `malloc`/`free` manual<br>*(Vazamentos e ponteiros pendentes)* | GC em execução<br>*(Pausas STW e inchaço de memória)* | Propriedade em compilação<br>*(Anotações explícitas `'a`)* | **Propriedade em compilação<br>(Zero-GC / Liberação determinística)** |
| **Sobrecarga de runtime** | Abstrações de custo zero | Pesada (motor GC + agendador) | Abstrações de custo zero | **Custo zero (Sem motor GC / Código de máquina nativo puro)** |
| **Carga cognitiva** | Vulnerável a UB e condições de corrida | Simples, mas pânicos de `nil` persistem | Curva íngreme (lutas com o borrow checker) | **Mínima (Sem anotações de lifetime / Fluxo simbólico limpo)** |
| **Modelo de concorrência** | Threads do SO / Bibliotecas externas | Corrotinas CSP (`go`) + canais (`chan`) | Threads / Runtimes Async (coloração de funções) | **Corrotinas leves nativas (`xu`) + `chan` tipados** |
| **Tratamento de erros** | Códigos de erro / Exceções *(Implícito)* | `if err != nil` *(Boilerplate repetitivo)* | `Result<T, E>` + operador `?` | **Fluxo simbólico: `>>` lança + `or` obrigatório** |
| **Controle de fluxo** | `return` / `break` / `continue` | `return` / `break` / `continue` | `return` / Expressões finais | **Fluxo simbólico: `<<` retorno / `>>` erro / `<-` quebra** |
| **Coesão da toolchain** | Fragmentada (CMake/Make/Conan) | Integrada de fábrica | Integrada (Cargo) | **Binário único (build/test/fmt/doc embutidos)** |
| **Instalação multiplataforma** | Dependências complexas de toolchain e linker | Instalador oficial / PATH manual | Exige rustup e scripts externos de rede | **Assistentes GUI autônomos / Instalação em um clique** |
| **Bare-metal e kernels** | Linkagem manual e asm inline, inseguro | Não suportado (preso a GC e runtime) | Suportado (`no_std`), mas lifetimes pesados | **Suporte nativo (`freestanding` / `#core`)<br>Destruição determinística Zero-GC + Lifetimes inferidos** |

---

<a id="quick-start"></a>
## 🚀 Início Rápido Sem Atrito

### Opção 1: Sandbox instantâneo no navegador (Sem instalação)

Acesse diretamente o **[Playground Online xulang.org](https://xulang.org/pt-br/playground/)**. O sandbox WebAssembly do lado do cliente oferece suporte a um subconjunto de Xu, incluindo tipos básicos, controle de fluxo, structs, diagnósticos de empréstimo e agendamento cooperativo de canais. Consulte o guia de recursos do playground para o escopo completo; multithreading real, E/S de rede, FFI C nativa e interface desktop requerem o SDK nativo.

### Opção 2: Instalação rápida em uma linha (Recomendado)

Xu oferece instaladores autônomos com compilador e código-fonte da biblioteca padrão embutidos, registrando automaticamente variáveis de ambiente persistentes do sistema:

- **macOS / Linux** (um comando no terminal):
  ```bash
  # Detecta a arquitetura, baixa e configura o ambiente automaticamente
  curl -fsSL https://xulang.org/install.sh | bash
  ```
  *Ou baixe os binários autônomos em [Releases](https://github.com/xulang-org/xu/releases):*
  ```bash
  chmod +x xu-setup-linux-x64 && ./xu-setup-linux-x64 -y
  ```

- **Windows** (Assistente GUI ou PowerShell):
  - **Assistente GUI**: Baixe `xu-setup-windows-x64.exe` em [Releases](https://github.com/xulang-org/xu/releases) e dê um duplo clique para executar o assistente gráfico sem dependências.
  - **Instalador de console ARM64**: Baixe `xu-setup-windows-arm64.exe` em [Releases](https://github.com/xulang-org/xu/releases) e execute `.\xu-setup-windows-arm64.exe --yes` no PowerShell.
  - Os instaladores do SDK declaram execução para o usuário atual e podem ser iniciados em um terminal comum. A instalação para todos os usuários ainda exige privilégios de administrador.
  - **Uma linha no PowerShell**:
    ```powershell
    irm https://xulang.org/install.ps1 | iex
    ```

> Abra um novo terminal e digite `xu --version` para executar de qualquer diretório.

### Opção 3: Hello World em 30 segundos

```bash
# 1. Crie o arquivo-fonte
cat << 'EOF' > main.xu
@main

fn main() int {
    println("Hello, World! Welcome to Xu.")
    << 0
}
EOF

# 2. Execute imediatamente
xu run main.xu

# 3. Compile AOT para um binário nativo otimizado
xu build main.xu -o myapp
./myapp
```

### Documentação

- [Primeiros passos](https://xulang.org/pt-br/docs/start/)
- [Referência CLI](https://xulang.org/pt-br/docs/cli/), incluindo otimização, testes e XACP
- [API da biblioteca padrão e pacotes](https://xulang.org/api/)
- [Módulos nativos e spans emprestados](https://xulang.org/pt-br/docs/native/)

A documentação e o código-fonte da API vivem em [xulang-org/xulang-org](https://github.com/xulang-org/xulang-org).

---

## Aplicações móveis (Phone)

O Xu 0.12.4 gera projetos de aplicativos ARM64 para dispositivos iOS, Simulador iOS e Android.

```sh
xu build app/ --phone --target ios-simulator-arm64 --bundle-id org.example.app -o build/ios
xu build app/ --phone --target android-arm64 --bundle-id org.example.app -o build/android
```

Cada saída contém um script de compilação da plataforma e um objeto de aplicativo Xu compilado. A camada de design `#ui/phone` inclui alvos de toque, navegação inferior, scaffolds adaptativos, cartões, linhas agrupadas e bottom sheets. O perfil de UI renderiza quadros Draw em um Canvas local do WebView do sistema e oferece suporte à entrada de texto via IME do sistema.
Consulte [Pré-requisitos e limites de Phone](src/ui/host/phone/README.md) e a [galeria de design móvel](examples/phone_gallery/README.md).

---

## 🖥️ Desenvolvimento de Kernels e Sistemas Operacionais Bare-Metal

Xu oferece suporte nativo a **kernels de sistemas operacionais, firmware embarcado e drivers bare-metal**. Por meio de uma arquitetura em camadas estritamente isolada, Xu preserva **destruição determinística Zero-GC** e **inferência implícita de propriedade (sem anotações manuais de lifetime)** no código normal, isolando a manipulação de hardware nos 5% inferiores do código:

* **Modo Freestanding sem host**:
  * A diretiva de código `$freestanding`, o manifesto de projeto `xu.xun` (`profile: freestanding`) ou as flags CLI `--profile=freestanding` / `--no-std` eliminam completamente dependências de syscalls do SO anfitrião, agendadores de runtime e libc.
* **Contratos de hardware estritamente isolados**:
  * **Ponteiros brutos (`*raw T`)**: A desreferenciação exige blocos explícitos `unsafe { ... }`; a inferência de propriedade e empréstimo ignora ponteiros brutos inteiramente, mantendo zero atrito no código de aplicação comum;
  * **Barreiras Volatile MMIO**: As primitivas integradas `volatile_read` e `volatile_write` evitam eliminação de código morto (DCE) e movimentação de invariantes de laço (LICM);
  * **Controle preciso de layout de memória**: `@repr("C", align: 4096)` para tabelas de diretório de páginas alinhadas em 4 KB (PML4 / Page Directory) e `@repr("C", packed)` para pacotes de rede de hardware e descritores de controle sem preenchimento.
* **Biblioteca de subsistema núcleo puramente estática (`#core`)**:
  * `#core/arch`: Instruções privilegiadas de CPU (`cli`, `sti`, `hlt`, `pause`, `wfi`), acesso a registradores de controle (`read_cr2/cr3`, `write_cr3`, `invlpg`, `set_vbar`, `set_trap_vector`), descritores de portas de interrupção IDT (`load_idt`), remapeamento do PIC 8259A (`pic_remap`) e inicialização do temporizador PIT 8254;
  * `#core/sync`: Spinlocks seguros contra interrupções `IrqSpinlock` e `Spinlock` acompanhados de guardas RAII `IrqGuard` e `SpinGuard` para **liberação determinística Zero-GC e restauração de interrupções ao sair do escopo**;
  * `#core/task`: `TaskContext` multiarquitetura de 192 bytes alinhado em 16 bytes, troca de contexto atômica (`switch_context`), snapshots completos de registradores (`TrapFrame`) e entradas de despacho de syscalls (`syscall_entry`);
  * `#core/virtio`: Framework de drivers VirtIO MMIO puramente estático, anéis de descritores VirtQueue, `VirtioBlkDriver` (dispositivo de bloco de disco) e `VirtioNetDriver` (placa de rede virtual);
  * `#core/mem` e `#core/alloc`: Intrínsecos de memória sem alocação (`memset`/`memcpy`/`memcmp`) e contratos de alocador conectável (`GlobalAlloc`).
* **Scaffolding instantâneo de projeto de kernel**:
  ```bash
  # Inicialize um novo projeto de kernel bare-metal (gera xu.xun, main.xu, linker.ld e Makefile multiarquitetura)
  xu init --baremetal my_os
  cd my_os

  # Compile binários ELF enxutos de kernel bare-metal entre arquiteturas (~1,9 KB a 2,4 KB)
  make
  # Ou execute diretamente no emulador QEMU
  make qemu
  ```

---

## 🗺️ Roadmap do Projeto

O SDK publicado é a linha de base deste roadmap. Consulte [Status e Limitações](https://xulang.org/pt-br/docs/status/) para os limites de runtime por plataforma alvo.

- [x] **Auto-hospedagem em Xu puro e AOT nativo**: Bootstrap a partir de um SDK Xu publicado, verificação de ponto fixo e emissão direta de código de máquina nativo e WebAssembly
- [x] **Propriedade e inferência de empréstimos em tempo de compilação**: Limpeza determinística de recursos; 0.9.4 conclui verificações para expressões aninhadas e arestas de retorno de laço
- [x] **Corrotinas e canais nativos**: Agendamento via palavra-chave `xu` aliado à comunicação `chan` tipada; portão de concorrência `select` multitarefa 100/100 aprovado
- [x] **Completude da suíte criptográfica**: Conformidade completa SM2/SM3/SM4/SM9; quadro de pilha do emparelhamento SM9 reduzido em 71,5% com zero avisos de compilação
- [x] **Fluxo simbólico e tratamento de erros**: Retorno `<<`, lançamento `>>` e guardas locais obrigatórias `or (err) { ... }`
- [x] **Geração de código multiplataforma**: Windows / macOS / Linux, ARM64 / x64 / LoongArch64 / RISC-V, WASM e alvos bare-metal
- [x] **Suporte a kernels de SO e bare-metal**: Perfil freestanding, subsistema puramente estático `#core` (arch/mem/sync/task/alloc/virtio), spinlocks seguros a interrupções, troca de contexto atômica, framework VirtIO e scaffolding em um comando (`xu init --baremetal`)
- [x] **Instalação e autoatualização do SDK**: Assistente Windows, PKG macOS, instalador multiplataforma em arquivo único e `xu up/update`
- [x] **Dependências de módulos reproduzíveis**: `init/get/install`, MVS, arquivos de lock/vendor, proxies, compilações offline/congeladas e cliente de checksum com chave confiável
- [x] **LSP e integração com editores**: `xu-lsp` e extensões VS Code/Cursor; diagnósticos, autocompletar, definições, hover, símbolos, referências, renomeação e formatação
- [x] **Genéricos e bases de otimização SSA**: Monomorfização sem o limite de quatro parâmetros de tipo, promoção escalar SSA, núcleos de laço SSA ARM64 e rotação de laços
- [x] **Diagnósticos e verificação do compilador**: Verificação MIR por passagem, dumps MIR, contadores de acerto de padrões e controles de padrões nomeados
- [x] **Pacotes de infraestrutura**: O módulo separado packages fornece 29 extensões incluindo MySQL, Postgres, Redis, ClickHouse, Kafka e SQLite
- [x] **Benchmarks multilíngues rastreáveis**: 72 cargas de trabalho em seis plataformas ARM64/x86-64, mantendo versões medidas de compiladores, procedência e verificação de saída
- [x] **Depurador interativo de código-fonte integrado**: `xu debug` controla breakpoints DWARF, pilhas de chamada e inspeção tipada de variáveis locais via LLDB/GDB com modo em lote não interativo
- [x] **Expansão avançada do otimizador**: Promoção escalar SSA mais profunda com provas de admissão de registros de structs, planejamento de tiles inspirado em TVM, LUT-GEMM de baixos bits e fusão em pipeline de operadores
- [ ] **Validação completa de runtime em máquinas alvo**: Portões de instalação do SDK nativo cobrem macOS ARM64/x64, Linux ARM64/x64 e Windows x64/ARM64. Ampliação contínua de verificações de biblioteca, rede, concorrência e UI desktop em cada alvo; SDKs LoongArch64 e RISC-V são compilados de forma cruzada.
- [ ] **Infraestrutura pública de pacotes**: Verificação de checksum com chave confiável, MVS e clientes proxy/vendor estão implementados. Serviços públicos de proxy/checksum e testemunhas independentes exigem implantação e validação de disponibilidade separadas.

---

## 🌟 Junte-se à Comunidade e Apoie o Xu

Xu é uma linguagem de programação de sistemas open source voltada para o futuro. Se você acredita em **desempenho extremo Zero-GC aliado a uma sintaxe moderna e ergonômica**, convidamos você a se juntar a nós!

- ⭐ **Dê uma Estrela ao repositório**: Se o Xu dialoga com a sua filosofia de engenharia, dê uma **Star** no [GitHub](https://github.com/xulang-org/xu) — isso impulsiona o nosso desenvolvimento!
- 💬 **Feedback e discussões**: Tem solicitações de recursos ou sugestões? Abra uma discussão ou issue no [GitHub Issues](https://github.com/xulang-org/xu/issues).
- 📊 **Insights de benchmarks**: Explore benchmarks profundos de CPU e memória em 72 cargas de trabalho em [xulang.org/pt-br/benchmarks](https://xulang.org/pt-br/benchmarks/).
- 📚 **Documentação completa**: Leia guias, especificações de sintaxe e tutoriais em [xulang.org](https://xulang.org/pt-br/).

---

## Licença

A linguagem de programação Xu é software livre sob a [Licença MIT](LICENSE).
