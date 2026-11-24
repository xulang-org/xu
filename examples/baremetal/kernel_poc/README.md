# Xu Baremetal Kernel (Stage 4: Interrupt Architecture, PIC/PIT, IDT & Hardware Control)

This baremetal kernel demonstrates the **Xu programming language** operating at baremetal hardware and operating system kernel levels.

## Architecture & Features

- **Freestanding Profile (`$freestanding` / `--profile=freestanding` / `--no-std`)**: Completely decoupled from host OS syscalls, runtime scheduling, and libc.
- **Hardware Abstraction Layer (HAL)**:
  - **Raw Pointers (`*raw T`) & `unsafe` Isolation**: Strict hardware memory access boundary; dereferencing raw pointers requires explicit `unsafe { ... }` blocks.
  - **Memory Layout Control**:
    - `@repr("C", align: 4096)`: 4096-byte aligned page tables (PML4 / Page Directory).
    - `@repr("C", packed)`: Zero-padding packed hardware network packets / descriptors.
  - **Volatile MMIO (`volatile_write` / `volatile_read`)**: Typed memory-mapped I/O access immune to dead-code elimination (DCE) and loop-invariant hoisting (LICM).
  - **Pure Core Foundation Library (`#core/arch`, `#core/mem`, `#core/alloc`, `#core/sync`, `#core/task`)**:
    - `core/arch`: CPU interrupt control (`cli`, `sti`, `hlt`, `pause`, `wfi`), port I/O (`in8`, `out8`, `in16`, `out16`, `in32`, `out32`), IDT management (`load_idt`), Control registers (`read_cr2`, `read_cr3`, `write_cr3`, `invlpg`), 8259A PIC remap/EOI, 8254 PIT timer.
    - `core/mem`: Zero-allocation memory operations (`memset`, `memcpy`, `memcmp`).
    - `core/sync`: Hardware interrupt-safe spinlocks (`Spinlock`, `IrqSpinlock`) and RAII scoped guards (`SpinGuard`, `IrqGuard`) with zero-GC deterministic `drop()`.
    - `core/task`: Cross-architecture 192-byte 16-byte aligned `TaskContext`, `TrapFrame` register snapshot, context switching (`switch_context`), and syscall entry (`syscall_entry`).
    - `core/alloc`: Pluggable physical and heap allocator contracts (`GlobalAlloc`).
- **Direct Multi-Architecture ELF64 Generation**:
  - `x86_64`: `x64-none` -> `kernel_x64.elf`
  - `AArch64`: `arm64-none` -> `kernel_arm64.elf`
  - `RISC-V 64`: `riscv64-none` -> `kernel_rv64.elf`

## Building and Running

### Build the Kernel ELF

Set standard paths and build across architectures:

```bash
# x86_64
xu build --profile=freestanding --target=x64-none examples/baremetal/kernel_poc/main.xu -o kernel_x64.elf

# AArch64
xu build --profile=freestanding --target=arm64-none examples/baremetal/kernel_poc/main.xu -o kernel_arm64.elf

# RISC-V 64
xu build --profile=freestanding --target=riscv64-none examples/baremetal/kernel_poc/main.xu -o kernel_rv64.elf
```

### Launch in QEMU

For x86_64:
```bash
qemu-system-x86_64 -kernel kernel_x64.elf -serial stdio -display none
```

Expected serial output:
```
====================================================
  Welcome to Xu Operating System (Baremetal Kernel) 
  Stage 3: Preemptive Multitasking & Synchronization
====================================================
[XU KERNEL] Booting in Freestanding Mode (no_std)...
[XU KERNEL] PageTable (4KB aligned) zeroed via #core/mem.
[XU KERNEL] Identity mapping entry configured (*raw u64).
[XU KERNEL] Ethernet header packed layout initialized.
[XU KERNEL] Scheduler initialized: Task 1 and Task 2 ready.
[XU KERNEL] Dispatching context switch: Main -> Task 1...
[TASK 1] Worker 1 active on CPU!
[TASK 1] Acquired IrqSpinlock inside critical section.
[TASK 1] Exited critical section; IrqSpinlock auto-released.
[TASK 1] Yielding execution to Task 2...
[TASK 2] Worker 2 active on CPU!
[TASK 2] Acquired Spinlock with RAII SpinGuard.
[TASK 2] Spinlock auto-released via deterministic drop().
[TASK 2] Yielding execution back to Main kernel...
[XU KERNEL] Resumed in Main kernel from Task 2!
[XU KERNEL] Multi-task context switching test PASSED!

[XU KERNEL] --- Starting Stage 4: Interrupts & Hardware Architecture ---
[XU KERNEL] Remapping 8259A PIC (IRQ 0-15 -> IDT vectors 32-47)...
[XU KERNEL] Programming 8254 PIT Timer to 100 Hz rate generator...
[XU KERNEL] IDT Entry 32 (Timer ISR) configured with gate attributes.
[XU KERNEL] LIDT executed: IDT base and limit loaded into CPU IDTR.
[XU KERNEL] Control Register CR3 read successfully.
[XU KERNEL] TrapFrame interrupt state initialized and verified.
[XU KERNEL] Stage 4 complete. Halting CPU cleanly. Goodbye from Xu!
```
