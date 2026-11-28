<p align="center">
  <a href="https://xulang.org/es/"><img src="brand/xu_classic.svg" alt="Xu Logo" width="100" height="100"></a>
</p>

<h1 align="center">El Lenguaje de Programación Xu</h1>

<p align="center">
  <b>La concurrencia al estilo Go se une al rendimiento Zero-GC de C/Rust</b><br>
  <sub>Un lenguaje de sistemas con seguridad de memoria en tiempo de compilación, diseñado para alto rendimiento, baja latencia y aplicaciones modernas.</sub>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ja.md">日本語</a> | <a href="README.ko.md">한국어</a> | <b>Español</b> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a> | <a href="README.ru.md">Русский</a> | <a href="README.pt-BR.md">Português</a>
</p>

<p align="center">
  <a href="https://github.com/xulang-org/xu/releases"><img src="https://img.shields.io/github/v/release/xulang-org/xu?label=Release&color=0284c7" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-emerald.svg" alt="License"></a>
  <a href="https://xulang.org/es/"><img src="https://img.shields.io/badge/Docs-xulang.org-rose" alt="Docs"></a>
  <a href="https://xulang.org/es/benchmarks/"><img src="https://img.shields.io/badge/Benchmarks-72%20Workloads-amber" alt="Benchmarks"></a>
  <a href="https://github.com/xulang-org/xu/actions/workflows/sdk.yml"><img src="https://github.com/xulang-org/xu/actions/workflows/sdk.yml/badge.svg" alt="SDK CI"></a>
</p>

<p align="center">
  <a href="https://xulang.org/es/playground/">🌐 <b>Playground en Línea (Sin Instalación)</b></a> &nbsp;•&nbsp;
  <a href="https://xulang.org/es/benchmarks/">⚡ <b>Panel de Benchmarks (72 Cargas)</b></a> &nbsp;•&nbsp;
  <a href="#quick-start">🚀 <b>Inicio Rápido en 30s</b></a> &nbsp;•&nbsp;
  <a href="RELEASES.md">📋 <b>Notas de Lanzamiento</b></a> &nbsp;•&nbsp;
  <a href="https://github.com/xulang-org/xu/releases">📦 <b>Descargar Instaladores</b></a>
</p>

---

> **Descargas oficiales del SDK**: [GitHub Releases](https://github.com/xulang-org/xu/releases) — Consulta las [Notas de Lanzamiento (RELEASES.md)](RELEASES.md) para ver el historial completo de cambios, cambios incompatibles y detalles de migración.

## ⚡ Xu de un Vistazo (Hechos, No Palabras)

Sin código repetitivo complejo. Sin acrobacias de anotaciones explícitas de tiempos de vida. Descubre la sintaxis limpia y moderna de Xu en 15 líneas de código:

```xu
@main
#errors

// Control de flujo simbólico: `<<` retorna, `>>` lanza errores; sin anidación de Result/unwrap
fn fetch_metric(task string) int {
    if task.len == 0 { >> errors.new("empty task name") }
    << task.len * 42
}

fn worker(task string, ch chan int) {
    val := fetch_metric(task) >>> (err) { << } // Manejo local seguro obligatorio sin `if err != nil`
    ch <- val                                 // Mensajería por canales con seguridad de tipos
}

fn main() int {
    ch := chan int{cap: 2}
    xu worker("latency", ch) // La palabra clave nativa `xu` lanza una corrutina ligera
    xu worker("memory", ch)
    println(<-ch + <-ch)     // Agregación fan-in mediante canales
    << 0                     // Liberación determinista, cero pausas de GC, compilación AOT nativa estática
}
```

> **Por qué encanta a los desarrolladores**:
> 1. **Control de flujo simbólico**: `<<` retorna, `>>` lanza errores, `<<<` sale. Adiós a las palabras clave verbosas heredadas.
> 2. **Flujo de errores ergonómico**: Gestionado en el punto de llamada con `>>> (err) { ... }` (o propagado con `>>>`). Elimina los interminables `if err != nil` y los fallos catastróficos de `unwrap()` en tiempo de ejecución.
> 3. **Concurrencia ligera nativa**: Corrutinas `xu worker()` + canales `chan` ofrecen concurrencia tan sencilla como en Go.
> 4. **Seguridad estática en compilación**: Verificada mediante inferencia de propiedad y préstamo. **Sin recolector de basura (Zero-GC)**, cero pausas y consumo de memoria determinista y ultraligero.

Un nombre de referencia escribible `r: $&T` puede satisfacer una expectativa `&T`: escribe `read(r)` o `let view: &T = r`. La vista compartida mantiene congelado al padre frente a escrituras y movimientos conflictivos hasta su último uso, incluidas vistas almacenadas y resultados de llamadas. Se rechazan los argumentos compartidos y escribibles conflictivos en una misma llamada. La degradación implícita requiere actualmente un nombre de referencia local y el mismo tipo directo apuntado. Declara una variable mutable una sola vez con `$x := value` (o `let $x: T = value`); usa simplemente `x` después. Los valores ordinarios requieren `&x` para un préstamo compartido o `$&x` para un préstamo escribible, cuyo tipo de referencia es `$&T`. Reutiliza nombres de referencia como `r`, o escribe `&*r` para un représtamo explícito. El préstamo automático desde valores ordinarios no está implementado.
Contratos de hardware de bajo nivel y bare-metal: los núcleos de sistemas operativos y controladores de dispositivos operan mediante punteros crudos `*raw T`, cuya desreferenciación exige bloques explícitos `unsafe { ... }` (p. ej. `p := addr as *raw u32; unsafe { *p = val }`), completamente omitidos por la inferencia de préstamo; MMIO utiliza barreras integradas `volatile_read` / `volatile_write`; la disposición de estructuras admite alineación `@repr("C", align: N)` y empaquetado sin relleno `@repr("C", packed)`; los archivos bare-metal especifican `$freestanding` para cortar toda dependencia de syscalls del host y de libc.

Consulta la [Guía de préstamo y modelo de memoria](https://xulang.org/es/docs/lang/memory/) para conocer las reglas vigentes.

---

## 🎯 Puntos de Dolor y «¿Por qué Xu?»

Como ingenieros de software que construimos sistemas y servicios de alto rendimiento, nos vemos obligados constantemente a elegir entre compromisos imperfectos:

### 1. Los dilemas que resolvemos

- **Problema 1: Picos de latencia del recolector de basura e hinchazón de memoria**
  - *Situación actual*: Go y Java son productivos, pero las pausas STW del GC y la latencia impredecible resultan inaceptables en pasarelas de baja latencia, motores de negociación y sistemas embebidos.
  - *Solución de Xu*: **Runtime Zero-GC**. Compilación AOT pura. La propiedad rastrea la memoria en tiempo de compilación y la libera de forma determinista al salir del ámbito. Cero pausas, cero picos de GC.
- **Problema 2: La batalla contra el «infierno de las anotaciones explícitas de lifetime»**
  - *Situación actual*: C/C++ expone a punteros colgantes, corrupción de memoria y errores UAF. Rust es seguro, pero los parámetros explícitos de tiempo de vida (`'a`, `'b`) y la gimnasia de tipos frenan drásticamente la velocidad de desarrollo.
  - *Solución de Xu*: **Inferencia implícita de propiedad y comprobación de préstamos**. Sin anotaciones explícitas de lifetime en código de aplicación. La semántica natural por valor para slices aporta seguridad y agilidad a la vez.
- **Problema 3: Código repetitivo que llena la pantalla y envoltorios de error anidados**
  - *Situación actual*: Los proyectos en Go se llenan de `if err != nil` repetitivos. Rust envuelve tipos en múltiples capas de `Result<T, E>` / `Option`.
  - *Solución de Xu*: **El operador simbólico `>>` combinado con el manejo obligatorio `>>> (err) { ... }`** ofrece una propagación de errores ligera, limpia y segura.
- **Problema 4: Cadenas de herramientas fragmentadas y fricción al instalar**
  - *Situación actual*: Ensamblar CMake, Make, gestores de paquetes y enlazadores de cada plataforma es notoriamente frágil.
  - *Solución de Xu*: **Ciclo cerrado en un solo binario**. Todo —compilador, ejecutor de pruebas, formateador (`xu fmt`), generador de documentación (`xu doc`) y asistentes gráficos GUI autoproducidos— viene integrado.

### 2. Comparativa técnica directa

| Dimensión clave | C / C++ | Go | Rust | **Xu** |
| :--- | :--- | :--- | :--- | :--- |
| **Gestión de memoria** | `malloc`/`free` manual<br>*(Fugas y punteros colgantes)* | GC en ejecución<br>*(Pausas STW e hinchazón de memoria)* | Propiedad en compilación<br>*(Anotaciones explícitas `'a`)* | **Propiedad en compilación<br>(Zero-GC / Liberación determinista)** |
| **Sobrecarga de runtime** | Abstracciones de coste cero | Pesada (motor GC + planificador) | Abstracciones de coste cero | **Coste cero (Sin motor GC / Código máquina nativo puro)** |
| **Carga cognitiva** | Vulnerable a UB y condiciones de carrera | Sencillo, pero persisten pánicos por `nil` | Curva empinada (lucha con el borrow checker) | **Mínima (Sin anotaciones de lifetime / Flujo simbólico limpio)** |
| **Modelo de concurrencia** | Hilos del SO / Bibliotecas externas | Corrutinas CSP (`go`) + canales (`chan`) | Hilos / Runtimes Async (coloreado de funciones) | **Corrutinas ligeras nativas (`xu`) + `chan` tipados** |
| **Manejo de errores** | Códigos de error / Excepciones *(Implícito)* | `if err != nil` *(Código repetitivo)* | `Result<T, E>` + operador `?` | **Flujo simbólico: `>>` lanzar + manejo obligatorio `or`** |
| **Control de flujo** | `return` / `break` / `continue` | `return` / `break` / `continue` | `return` / Expresiones finales | **Flujo simbólico: `<<` retornar / `>>` error / `<-` salir** |
| **Cohesión de herramientas**| Fragmentada (CMake/Make/Conan) | Integrada de serie | Integrada (Cargo) | **Ciclo en un binario (build/test/fmt/doc integrados)** |
| **Instalación multiplataforma**| Dependencias complejas de toolchain y linker | Instalador oficial / PATH manual | Requiere rustup y scripts de red externos | **Asistentes GUI autónomos / Instalación en un clic** |
| **Bare-metal y kernels** | Enlazado manual y asm inline, inseguro | No soportado (atado a GC y runtime) | Soportado (`no_std`), pero lifetimes pesados | **Soporte nativo (`freestanding` / `#core`)<br>Destrucción determinista Zero-GC + Lifetimes inferidos** |

---

<a id="quick-start"></a>
## 🚀 Inicio Rápido Sin Fricción

### Opción 1: Sandbox instantáneo en el navegador (Sin instalación)

Entra directamente al **[Playground en Línea de xulang.org](https://xulang.org/es/playground/)**. El sandbox WebAssembly del lado del cliente admite un subconjunto de Xu que incluye tipos básicos, control de flujo, estructuras, diagnósticos de préstamo y planificación cooperativa de canales. Consulta la guía de capacidades del playground para conocer su alcance; el multihilo real, la E/S de red, la FFI nativa en C y la interfaz de escritorio requieren el SDK nativo.

### Opción 2: Instalación rápida en una línea (Recomendado)

Xu ofrece instaladores autónomos con el compilador y el código fuente de la biblioteca estándar integrados, registrando automáticamente las variables de entorno persistentes:

- **macOS / Linux** (un comando en terminal):
  ```bash
  # Detecta la arquitectura, descarga y configura el entorno automáticamente
  curl -fsSL https://xulang.org/install.sh | bash
  ```
  *O descarga los binarios autónomos desde [Releases](https://github.com/xulang-org/xu/releases):*
  ```bash
  chmod +x xu-setup-linux-x64 && ./xu-setup-linux-x64 -y
  ```

- **Windows** (Asistente GUI o PowerShell):
  - **Asistente GUI**: Descarga `xu-setup-windows-x64.exe` desde [Releases](https://github.com/xulang-org/xu/releases) y haz doble clic para iniciar el asistente gráfico sin dependencias.
  - **Instalador de consola ARM64**: Descarga `xu-setup-windows-arm64.exe` desde [Releases](https://github.com/xulang-org/xu/releases) y ejecuta `.\xu-setup-windows-arm64.exe --yes` en PowerShell.
  - Los instaladores del SDK declaran ejecución para el usuario actual y pueden iniciarse desde una terminal normal. Instalar para todos los usuarios sigue requiriendo privilegios de administrador.
  - **Una línea en PowerShell**:
    ```powershell
    irm https://xulang.org/install.ps1 | iex
    ```

> Abre una nueva terminal y escribe `xu --version` para ejecutarlo desde cualquier ubicación.

### Opción 3: Hello World en 30 segundos

```bash
# 1. Crea el archivo fuente
cat << 'EOF' > main.xu
@main

fn main() int {
    println("Hello, World! Welcome to Xu.")
    << 0
}
EOF

# 2. Ejecuta inmediatamente
xu run main.xu

# 3. Compila AOT a un binario nativo optimizado
xu build main.xu -o myapp
./myapp
```

### Documentación

- [Primeros pasos](https://xulang.org/es/docs/start/)
- [Referencia CLI](https://xulang.org/es/docs/cli/), incluyendo optimización, pruebas y XACP
- [API de biblioteca estándar y paquetes](https://xulang.org/api/)
- [Módulos nativos y spans prestados](https://xulang.org/es/docs/native/)

La documentación y el código fuente de la API se mantienen en [xulang-org/xulang-org](https://github.com/xulang-org/xulang-org).

---

## Aplicaciones móviles (Phone)

Xu 0.12.4 genera proyectos de aplicaciones ARM64 para dispositivos iOS, el Simulador de iOS y Android.

```sh
xu build app/ --phone --target ios-simulator-arm64 --bundle-id org.example.app -o build/ios
xu build app/ --phone --target android-arm64 --bundle-id org.example.app -o build/android
```

Cada salida contiene un script de compilación para la plataforma y un objeto de aplicación Xu compilado. La capa de diseño `#ui/phone` incluye objetivos táctiles, navegación inferior, plantillas adaptativas, tarjetas, filas agrupadas y hojas inferiores. El perfil de UI dibuja fotogramas Draw en un Canvas local del WebView del sistema y admite entrada de texto mediante el IME del sistema.
Consulta los [requisitos y límites de Phone](src/ui/host/phone/README.md) y la [galería de diseño móvil](examples/phone_gallery/README.md).

---

## 🖥️ Desarrollo de Kernels y Sistemas Operativos Bare-Metal

Xu ofrece soporte nativo para **núcleos de sistemas operativos, firmware embebido y controladores bare-metal**. Mediante una arquitectura por capas estrictamente aislada, Xu conserva la **destrucción determinista Zero-GC** y la **inferencia implícita de propiedad (sin anotaciones manuales de lifetime)** en el código habitual, aislando la manipulación de hardware en el 5 % inferior del código:

* **Modo Freestanding sin host**:
  * La directiva de código `$freestanding`, el manifiesto de proyecto `xu.xun` (`profile: freestanding`) o las banderas CLI `--profile=freestanding` / `--no-std` cortan por completo las dependencias con las syscalls del SO anfitrión, el planificador del runtime y libc.
* **Contratos de hardware estrictamente aislados**:
  * **Punteros crudos (`*raw T`)**: La desreferenciación exige bloques explícitos `unsafe { ... }`; la inferencia de propiedad y préstamo omite los punteros crudos por completo, manteniendo cero fricción en el código de aplicación normal;
  * **Barreras Volatile MMIO**: Las primitivas integradas `volatile_read` y `volatile_write` evitan la eliminación de código muerto (DCE) y el izado de invariantes de bucle (LICM);
  * **Control preciso de disposición en memoria**: `@repr("C", align: 4096)` para tablas de páginas alineadas a 4 KB (PML4 / Page Directory) y `@repr("C", packed)` para paquetes de red de hardware y descriptores de control sin relleno.
* **Biblioteca de subsistema núcleo puramente estática (`#core`)**:
  * `#core/arch`: Instrucciones privilegiadas de CPU (`cli`, `sti`, `hlt`, `pause`, `wfi`), acceso a registros de control (`read_cr2/cr3`, `write_cr3`, `invlpg`, `set_vbar`, `set_trap_vector`), descriptores de puertas de interrupción IDT (`load_idt`), remapeo del PIC 8259A (`pic_remap`) e inicialización del temporizador PIT 8254;
  * `#core/sync`: Spinlocks seguros frente a interrupciones `IrqSpinlock` y `Spinlock` junto con guardas RAII `IrqGuard` y `SpinGuard` para **liberación determinista Zero-GC y restauración de interrupciones al salir del ámbito**;
  * `#core/task`: `TaskContext` multiarquitectura de 192 bytes alineado a 16 bytes, cambio de contexto atómico (`switch_context`), estructuras completas de captura de registros (`TrapFrame`) y puntos de despacho de llamadas al sistema (`syscall_entry`);
  * `#core/virtio`: Framework de controladores VirtIO MMIO puramente estático, anillos de descriptores VirtQueue, `VirtioBlkDriver` (dispositivo de bloque de disco) y `VirtioNetDriver` (tarjeta de red virtual);
  * `#core/mem` y `#core/alloc`: Intrínsecos de memoria sin asignaciones (`memset`/`memcpy`/`memcmp`) y contratos de asignador conectable (`GlobalAlloc`).
* **Plantilla instantánea para proyectos de kernel**:
  ```bash
  # Inicializa un nuevo proyecto de kernel bare-metal (genera xu.xun, main.xu, linker.ld y Makefile multiarquitectura)
  xu init --baremetal my_os
  cd my_os

  # Compila binarios ELF minimalistas de kernel bare-metal multiarquitectura (~1.9 KB a 2.4 KB)
  make
  # O ejecútalo directamente en el emulador QEMU
  make qemu
  ```

---

## 🗺️ Hoja de Ruta del Proyecto

El SDK publicado es la línea base de esta hoja de ruta. Consulta [Estado y Limitaciones](https://xulang.org/es/docs/status/) para conocer los límites de ejecución específicos de cada plataforma.

- [x] **Auto-hospedaje en Xu puro y AOT nativo**: Arrancar desde un SDK de Xu publicado, verificar punto fijo y emitir directamente código máquina nativo y WebAssembly
- [x] **Propiedad e inferencia de préstamos en tiempo de compilación**: Limpieza determinista de recursos; 0.9.4 completa la verificación en expresiones anidadas y aristas de retorno de bucles
- [x] **Corrutinas y canales nativos**: Planificación mediante la palabra clave `xu` con comunicación `chan` tipada; compuerta de concurrencia `select` multitarea 100/100 superada
- [x] **Suite criptográfica completa**: Conformidad completa con SM2/SM3/SM4/SM9; marco de pila de emparejamiento SM9 reducido en un 71.5 % sin advertencias de compilación
- [x] **Flujo simbólico y manejo de errores**: Retorno `<<`, lanzamiento `>>` y guardas locales obligatorias `>>> (err) { ... }`
- [x] **Generación de código multiplataforma**: Windows / macOS / Linux, ARM64 / x64 / LoongArch64 / RISC-V, WASM y objetivos bare-metal
- [x] **Soporte de kernels de SO y bare-metal**: Perfil de compilación freestanding, subsistema estático puro `#core` (arch/mem/sync/task/alloc/virtio), spinlocks seguros ante interrupciones, cambio de contexto atómico, framework VirtIO y plantilla en un comando (`xu init --baremetal`)
- [x] **Instalación y autoactualización del SDK**: Asistente Windows, PKG de macOS, instalador multiplataforma de archivo único y `xu up/update`
- [x] **Dependencias de módulos reproducibles**: `init/get/install`, MVS, archivos de bloqueo/vendor, proxies, compilaciones offline/congeladas y cliente de sumas de verificación con clave confiable
- [x] **LSP e integración con editores**: `xu-lsp` y extensiones para VS Code/Cursor; diagnósticos, autocompletado, definiciones, hover, símbolos, referencias, renombrado y formateo
- [x] **Genéricos y base de optimización SSA**: Monomorfización sin el límite de cuatro parámetros de tipo, promoción escalar SSA, núcleos de bucle SSA en ARM64 y rotación de bucles
- [x] **Diagnósticos y verificación del compilador**: Verificación MIR por pase, volcados MIR, contadores de aciertos de patrones y controles de patrones con nombre
- [x] **Paquetes de infraestructura**: El módulo independiente packages ofrece 29 extensiones que incluyen MySQL, Postgres, Redis, ClickHouse, Kafka y SQLite
- [x] **Benchmarks multilenguaje trazables**: 72 cargas de trabajo en seis plataformas ARM64/x86-64, conservando versiones de compilador medidas, procedencia y verificación de salida
- [x] **Depurador de código fuente interactivo integrado**: `xu debug` controla puntos de interrupción DWARF, pilas de llamadas e inspección de variables locales tipadas mediante LLDB/GDB con modo por lotes no interactivo
- [x] **Expansión avanzada del optimizador**: Promoción escalar SSA más profunda con pruebas de admisión de registros de estructuras, planificación de tiles inspirada en TVM, LUT-GEMM de bajos bits y fusión canalizada de operadores
- [ ] **Validación completa de runtime en máquinas destino**: Las puertas de instalación del SDK nativo cubren macOS ARM64/x64, Linux ARM64/x64 y Windows x64/ARM64. Ampliación de pruebas de bibliotecas, red, concurrencia y UI de escritorio en cada objetivo; los SDK de LoongArch64 y RISC-V se compilan de forma cruzada.
- [ ] **Infraestructura pública de paquetes**: La verificación de sumas con clave confiable, MVS y clientes proxy/vendor están implementados. Los servicios públicos de proxy/checksum y testigos independientes requieren despliegue y validación de disponibilidad por separado.

---

## 🌟 Únete a la Comunidad y Apoya a Xu

Xu es un lenguaje de programación de sistemas de código abierto orientado al futuro. Si crees en **el rendimiento extremo Zero-GC combinado con una sintaxis moderna y ergonómica**, ¡te invitamos a unirte!

- ⭐ **Dale una Estrella al repositorio**: Si Xu conecta con tu filosofía de ingeniería, danos una **Star** en [GitHub](https://github.com/xulang-org/xu) — ¡impulsa nuestro desarrollo!
- 💬 **Comentarios y debates**: ¿Tienes solicitudes de funciones o sugerencias? Abre una discusión o ticket en [GitHub Issues](https://github.com/xulang-org/xu/issues).
- 📊 **Análisis de benchmarks**: Explora comparativas detalladas de CPU y memoria en 72 cargas de trabajo en [xulang.org/es/benchmarks](https://xulang.org/es/benchmarks/).
- 📚 **Documentación completa**: Lee guías, especificaciones de sintaxis y tutoriales en [xulang.org](https://xulang.org/es/).

---

## Licencia

El lenguaje de programación Xu es software de código abierto bajo la [Licencia MIT](LICENSE).
