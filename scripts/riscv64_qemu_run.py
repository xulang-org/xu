#!/usr/bin/env python3
"""riscv64 QEMU runner: wrap a linux-riscv64 static ELF with a minimal
M-mode semihosting shim (mtvec + mmap/write/exit ecall) and run under
qemu-system-riscv64 -M virt -bios none -kernel.

QEMU virt reset ROM jumps to 0x80000000 (not ELF e_entry). The shim is
placed there and jumps to the guest e_entry. Guest PT_LOADs keep their
original vaddrs (typically 0x80001000+).

Usage: riscv64_qemu_run.py <a.out> [timeout_seconds]
"""
import struct, subprocess, sys, os, time

def r_type(op, rd, f3, rs1, rs2, f7=0):
    return (op | ((rd & 31) << 7) | ((f3 & 7) << 12) | ((rs1 & 31) << 15)
            | ((rs2 & 31) << 20) | ((f7 & 0x7f) << 25))

def i_type(op, rd, f3, rs1, imm):
    return op | ((rd & 31) << 7) | ((f3 & 7) << 12) | ((rs1 & 31) << 15) | ((imm & 0xfff) << 20)

def s_type(op, f3, rs1, rs2, imm):
    return (op | ((imm & 0x1f) << 7) | ((f3 & 7) << 12) | ((rs1 & 31) << 15)
            | ((rs2 & 31) << 20) | (((imm >> 5) & 0x7f) << 25))

def u_type(op, rd, imm20):
    return op | ((rd & 31) << 7) | ((imm20 & 0xfffff) << 12)

def b_type(op, f3, rs1, rs2, imm):
    imm &= 0x1fff
    return (op | (((imm >> 11) & 1) << 7) | (((imm >> 1) & 0xf) << 8)
            | ((f3 & 7) << 12) | ((rs1 & 31) << 15) | ((rs2 & 31) << 20)
            | (((imm >> 5) & 0x3f) << 25) | (((imm >> 12) & 1) << 31))

def j_type(op, rd, imm):
    imm &= 0x1fffff
    return (op | ((rd & 31) << 7) | (((imm >> 12) & 0xff) << 12)
            | (((imm >> 11) & 1) << 20) | (((imm >> 1) & 0x3ff) << 21)
            | (((imm >> 20) & 1) << 31))

def lui_addi(rd, val):
    """Materialize a 32-bit address into rd.

    RV64 `lui` sign-extends imm[31:12] into xlen, so any DRAM address in the
    virt machine window (0x80000000+) becomes 0xffffffff8xxxxxxx. Zero-extend
    the low 32 bits with slli/srli after lui+addi.
    """
    val &= 0xffffffff
    hi = ((val + 0x800) >> 12) & 0xfffff
    lo = val - (((val + 0x800) >> 12) << 12)
    return [
        u_type(0x37, rd, hi),
        i_type(0x13, rd, 0, rd, lo & 0xfff),
        i_type(0x13, rd, 1, rd, 32),   # slli rd, rd, 32
        i_type(0x13, rd, 5, rd, 32),   # srli rd, rd, 32
    ]

zero, ra, sp = 0, 1, 2
t0, t1, t2 = 5, 6, 7
a0, a1, a2, a3, a4, a5, a7 = 10, 11, 12, 13, 14, 15, 17
t3, t4, t5 = 28, 29, 30

SHIM_BASE = 0x80000000
UART_BASE = 0x10000000
EXIT_ADDR = 0x80000ff0
BUMP_ADDR = 0x80000ff8
BUMP_START = 0x81000000
STACK_TOP = 0x80f00000
# Single-file ramdisk for openat/read/write/close (file_roundtrip).
FILE_LEN_ADDR = 0x80000e00
FILE_POS_ADDR = 0x80000e08
FILE_BUF = 0x82000000
# Sync "clone": run child to thread-exit, then resume parent (buffered chan).
CLONE_FLAG = 0x80000b00
CTX_BASE = 0x80000c00  # [0]=mepc_resume, [8*i]=x_i for i=1..31


def build_shim(entry):
    labels, code, pending = {}, [], []

    def emit(w):
        code.append(w & 0xffffffff)

    def L(n):
        labels[n] = len(code)

    def la(rd, lab):
        pending.append((len(code), 'la', rd, lab))
        for _ in range(4):
            emit(0)

    def jal_zero(lab):
        pending.append((len(code), 'jal', 0, lab))
        emit(0)

    def beq(rs1, rs2, lab):
        pending.append((len(code), 'beq', rs1, rs2, lab))
        emit(0)

    def bne(rs1, rs2, lab):
        pending.append((len(code), 'bne', rs1, rs2, lab))
        emit(0)

    L('start')
    la(t0, 'handler')
    # csrw mtvec, t0  (csr=0x305, funct3=1, rd=0, rs1=t0)
    emit(i_type(0x73, 0, 1, t0, 0x305))

    # The shim enters the guest directly in M-mode, without a Linux kernel to
    # enable floating-point state. FS=Off turns the first RV64D instruction
    # into an illegal-instruction trap and the generic handler halts forever.
    # Mark FS=Dirty (mstatus[14:13]=11) before jumping to the ELF entry.
    emit(i_type(0x73, t0, 2, zero, 0x300))  # csrr t0, mstatus
    emit(u_type(0x37, t1, 6))                # lui t1, 0x6 -> 0x6000
    emit(r_type(0x33, t0, 6, t0, t1, 0))    # or t0, t0, t1
    emit(i_type(0x73, zero, 1, t0, 0x300))  # csrw mstatus, t0

    for w in lui_addi(sp, STACK_TOP):
        emit(w)
    emit(s_type(0x23, 3, sp, zero, 0))
    emit(s_type(0x23, 3, sp, zero, 8))
    emit(s_type(0x23, 3, sp, zero, 16))
    emit(s_type(0x23, 3, sp, zero, 24))

    for w in lui_addi(t0, EXIT_ADDR):
        emit(w)
    emit(i_type(0x13, t1, 0, zero, -1))
    emit(s_type(0x23, 3, t0, t1, 0))

    for w in lui_addi(t0, BUMP_ADDR):
        emit(w)
    for w in lui_addi(t1, BUMP_START):
        emit(w)
    emit(s_type(0x23, 3, t0, t1, 0))

    # ramdisk meta: len=0, pos=0
    for w in lui_addi(t0, FILE_LEN_ADDR):
        emit(w)
    emit(s_type(0x23, 3, t0, zero, 0))
    for w in lui_addi(t0, FILE_POS_ADDR):
        emit(w)
    emit(s_type(0x23, 3, t0, zero, 0))
    for w in lui_addi(t0, CLONE_FLAG):
        emit(w)
    emit(s_type(0x23, 3, t0, zero, 0))

    for w in lui_addi(t0, entry & 0xffffffff):
        emit(w)
    emit(i_type(0x67, zero, 0, t0, 0))  # jalr zero, t0, 0

    L('handler')
    # Park t0/t1 first — needed both to read CLONE_FLAG and to snapshot them.
    emit(s_type(0x23, 3, sp, t0, -8))
    emit(s_type(0x23, 3, sp, t1, -16))
    for w in lui_addi(t0, CLONE_FLAG):
        emit(w)
    emit(i_type(0x03, t1, 3, t0, 0))
    bne(t1, zero, 'dispatch')
    # Parent (or idle) snapshot: CTX[0]=mepc, CTX[8*i]=x_i.
    emit(s_type(0x23, 3, sp, t3, -24))
    emit(s_type(0x23, 3, sp, t4, -32))
    for w in lui_addi(t3, CTX_BASE):
        emit(w)
    emit(i_type(0x73, t4, 2, zero, 0x341))
    emit(s_type(0x23, 3, t3, t4, 0))
    for xi in range(1, 32):
        if xi in (t0, t1, t3, t4):
            continue
        emit(s_type(0x23, 3, t3, xi, xi * 8))
    emit(i_type(0x03, t4, 3, sp, -8))    # orig t0
    emit(s_type(0x23, 3, t3, t4, t0 * 8))
    emit(i_type(0x03, t4, 3, sp, -16))   # orig t1
    emit(s_type(0x23, 3, t3, t4, t1 * 8))
    emit(i_type(0x03, t4, 3, sp, -24))   # orig t3
    emit(s_type(0x23, 3, t3, t4, t3 * 8))
    emit(i_type(0x03, t4, 3, sp, -32))   # orig t4
    emit(s_type(0x23, 3, t3, t4, t4 * 8))

    L('dispatch')
    # csrr t0, mcause (0x342) — only Environment Call from M-mode
    emit(i_type(0x73, t0, 2, zero, 0x342))
    emit(i_type(0x13, t1, 0, zero, 11))
    bne(t0, t1, 'halt')

    emit(i_type(0x13, t0, 0, zero, 222))
    beq(a7, t0, 'do_mmap')
    emit(i_type(0x13, t0, 0, zero, 64))
    beq(a7, t0, 'do_write')
    emit(i_type(0x13, t0, 0, zero, 63))
    beq(a7, t0, 'do_read')
    emit(i_type(0x13, t0, 0, zero, 56))
    beq(a7, t0, 'do_openat')
    emit(i_type(0x13, t0, 0, zero, 57))
    beq(a7, t0, 'do_close')
    emit(i_type(0x13, t0, 0, zero, 220))
    beq(a7, t0, 'do_clone')
    emit(i_type(0x13, t0, 0, zero, 98))
    beq(a7, t0, 'do_futex')
    emit(i_type(0x13, t0, 0, zero, 93))
    beq(a7, t0, 'do_exit_thread')
    emit(i_type(0x13, t0, 0, zero, 94))
    beq(a7, t0, 'do_exit_group')
    emit(i_type(0x13, a0, 0, zero, 0))
    jal_zero('return_')

    L('do_mmap')
    emit(i_type(0x13, t0, 0, a1, -1))
    emit(i_type(0x13, t0, 5, t0, 12))  # srli
    emit(i_type(0x13, t0, 0, t0, 1))
    emit(i_type(0x13, t0, 1, t0, 12))  # slli
    for w in lui_addi(t1, BUMP_ADDR):
        emit(w)
    emit(i_type(0x03, t2, 3, t1, 0))  # ld
    emit(i_type(0x13, a0, 0, t2, 0))
    emit(r_type(0x33, t2, 0, t2, t0, 0))  # add
    emit(s_type(0x23, 3, t1, t2, 0))
    jal_zero('return_')

    L('do_openat')  # openat(dirfd, path, flags, mode) -> fd 3
    # O_TRUNC (0x200) clears content; always reset read cursor.
    emit(i_type(0x13, t0, 0, zero, 0x200))
    emit(r_type(0x33, t0, 7, a2, t0, 0))  # and flags, O_TRUNC
    beq(t0, zero, 'open_keep')
    for w in lui_addi(t1, FILE_LEN_ADDR):
        emit(w)
    emit(s_type(0x23, 3, t1, zero, 0))
    L('open_keep')
    for w in lui_addi(t1, FILE_POS_ADDR):
        emit(w)
    emit(s_type(0x23, 3, t1, zero, 0))
    emit(i_type(0x13, a0, 0, zero, 3))
    jal_zero('return_')

    L('do_close')
    emit(i_type(0x13, a0, 0, zero, 0))
    jal_zero('return_')

    L('do_write')
    emit(i_type(0x13, t0, 0, zero, 3))
    beq(a0, t0, 'file_write')
    # stdout/stderr -> UART
    for w in lui_addi(t3, UART_BASE):
        emit(w)
    emit(i_type(0x13, t4, 0, a2, 0))
    emit(i_type(0x13, t5, 0, a1, 0))
    L('wloop')
    beq(t4, zero, 'wdone')
    L('wwait')
    emit(i_type(0x03, t0, 4, t3, 5))  # lbu LSR
    emit(i_type(0x13, t1, 0, zero, 0x20))
    emit(r_type(0x33, t0, 7, t0, t1, 0))  # and
    beq(t0, zero, 'wwait')
    emit(i_type(0x03, t0, 4, t5, 0))  # lbu
    emit(s_type(0x23, 0, t3, t0, 0))  # sb THR
    emit(i_type(0x13, t5, 0, t5, 1))
    emit(i_type(0x13, t4, 0, t4, -1))
    jal_zero('wloop')
    L('wdone')
    emit(i_type(0x13, a0, 0, a2, 0))
    jal_zero('return_')

    L('file_write')  # append a2 bytes from a1 at FILE_BUF+FILE_LEN
    for w in lui_addi(t0, FILE_LEN_ADDR):
        emit(w)
    emit(i_type(0x03, t1, 3, t0, 0))  # t1 = len
    for w in lui_addi(t2, FILE_BUF):
        emit(w)
    emit(r_type(0x33, t2, 0, t2, t1, 0))  # dst
    emit(i_type(0x13, a3, 0, a1, 0))  # src
    emit(i_type(0x13, a4, 0, a2, 0))  # n
    L('fwloop')
    beq(a4, zero, 'fwdone')
    emit(i_type(0x03, t3, 4, a3, 0))  # lbu
    emit(s_type(0x23, 0, t2, t3, 0))  # sb
    emit(i_type(0x13, a3, 0, a3, 1))
    emit(i_type(0x13, t2, 0, t2, 1))
    emit(i_type(0x13, a4, 0, a4, -1))
    jal_zero('fwloop')
    L('fwdone')
    emit(r_type(0x33, t1, 0, t1, a2, 0))  # len += n
    emit(s_type(0x23, 3, t0, t1, 0))
    emit(i_type(0x13, a0, 0, a2, 0))
    jal_zero('return_')

    L('do_read')
    emit(i_type(0x13, t0, 0, zero, 3))
    bne(a0, t0, 'read_bad')
    for w in lui_addi(t0, FILE_LEN_ADDR):
        emit(w)
    emit(i_type(0x03, t1, 3, t0, 0))  # len
    for w in lui_addi(t0, FILE_POS_ADDR):
        emit(w)
    emit(i_type(0x03, t2, 3, t0, 0))  # pos
    emit(r_type(0x33, t3, 0, t1, t2, 0x20))  # sub: remaining = len-pos (f7=0x20)
    # n = min(a2, remaining); if remaining==0 return 0
    beq(t3, zero, 'read_eof')
    emit(r_type(0x33, t4, 2, a2, t3, 0))  # slt t4 = (a2 < rem)
    bne(t4, zero, 'read_use_a2')
    emit(i_type(0x13, a5, 0, t3, 0))  # n = rem
    jal_zero('read_copy')
    L('read_use_a2')
    emit(i_type(0x13, a5, 0, a2, 0))
    L('read_copy')
    for w in lui_addi(t1, FILE_BUF):
        emit(w)
    emit(r_type(0x33, t1, 0, t1, t2, 0))  # src = buf+pos
    emit(i_type(0x13, a3, 0, a1, 0))  # dst
    emit(i_type(0x13, a4, 0, a5, 0))  # n
    L('frloop')
    beq(a4, zero, 'frdone')
    emit(i_type(0x03, t3, 4, t1, 0))
    emit(s_type(0x23, 0, a3, t3, 0))
    emit(i_type(0x13, t1, 0, t1, 1))
    emit(i_type(0x13, a3, 0, a3, 1))
    emit(i_type(0x13, a4, 0, a4, -1))
    jal_zero('frloop')
    L('frdone')
    emit(r_type(0x33, t2, 0, t2, a5, 0))  # pos += n
    emit(s_type(0x23, 3, t0, t2, 0))
    emit(i_type(0x13, a0, 0, a5, 0))
    jal_zero('return_')
    L('read_eof')
    emit(i_type(0x13, a0, 0, zero, 0))
    jal_zero('return_')
    L('read_bad')
    emit(i_type(0x13, a0, 0, zero, -9))  # -EBADF
    jal_zero('return_')

    L('do_futex')
    # Single-threaded shim: WAIT/WAKE are no-ops (return 0).
    emit(i_type(0x13, a0, 0, zero, 0))
    jal_zero('return_')

    L('do_clone')
    # Parent image already in CTX. Switch to child stack (saved a1), return 0.
    for w in lui_addi(t0, CTX_BASE):
        emit(w)
    emit(i_type(0x03, sp, 3, t0, a1 * 8))  # sp = saved a1 (child stack)
    for w in lui_addi(t0, CLONE_FLAG):
        emit(w)
    emit(i_type(0x13, t1, 0, zero, 1))
    emit(s_type(0x23, 3, t0, t1, 0))
    emit(i_type(0x13, a0, 0, zero, 0))
    jal_zero('return_')

    L('do_exit_thread')
    for w in lui_addi(t0, CLONE_FLAG):
        emit(w)
    emit(i_type(0x03, t1, 3, t0, 0))
    beq(t1, zero, 'do_exit_group')
    emit(s_type(0x23, 3, t0, zero, 0))
    for w in lui_addi(t0, CTX_BASE):
        emit(w)
    emit(i_type(0x03, t1, 3, t0, 0))  # parent mepc
    emit(i_type(0x13, t1, 0, t1, 4))  # skip ecall
    for xi in range(1, 32):
        if xi in (a0, t0, t1):
            continue
        emit(i_type(0x03, xi, 3, t0, xi * 8))
    emit(i_type(0x13, a0, 0, zero, 2))  # fake tid
    emit(i_type(0x73, zero, 1, t1, 0x341))  # csrw mepc
    emit(0x30200073)  # mret

    L('do_exit_group')
    for w in lui_addi(t0, EXIT_ADDR):
        emit(w)
    emit(s_type(0x23, 3, t0, a0, 0))
    L('halt')
    jal_zero('halt')

    L('return_')
    emit(i_type(0x73, t0, 2, zero, 0x341))  # csrr mepc
    emit(i_type(0x13, t0, 0, t0, 4))
    emit(i_type(0x73, zero, 1, t0, 0x341))  # csrw mepc
    emit(0x30200073)  # mret

    for item in pending:
        kind = item[1]
        if kind == 'la':
            i_idx, _, rd, lab = item
            tgt = SHIM_BASE + labels[lab] * 4
            words = lui_addi(rd, tgt)
            for k, w in enumerate(words):
                code[i_idx + k] = w
        elif kind == 'jal':
            i_idx, _, rd, lab = item
            imm = (labels[lab] - i_idx) * 4
            code[i_idx] = j_type(0x6f, rd, imm)
        elif kind == 'beq':
            i_idx, _, rs1, rs2, lab = item
            imm = (labels[lab] - i_idx) * 4
            code[i_idx] = b_type(0x63, 0, rs1, rs2, imm)
        elif kind == 'bne':
            i_idx, _, rs1, rs2, lab = item
            imm = (labels[lab] - i_idx) * 4
            code[i_idx] = b_type(0x63, 1, rs1, rs2, imm)

    return b''.join(struct.pack('<I', w) for w in code)


def read_elf(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'\x7fELF'
    entry = struct.unpack_from('<Q', d, 24)[0]
    phoff = struct.unpack_from('<Q', d, 32)[0]
    phnum = struct.unpack_from('<H', d, 56)[0]
    segs = []
    for i in range(phnum):
        off = phoff + i * 56
        t, fl = struct.unpack_from('<II', d, off)
        po, pv, _pp, fs, ms, _al = struct.unpack_from('<QQQQQQ', d, off + 8)
        if t == 1:
            segs.append((po, pv, fs, ms, fl))
    return entry, segs, d


def combine(elfpath, outpath):
    entry, segs, d = read_elf(elfpath)
    sb = build_shim(entry)
    shim_off = 0x1000
    for (_, pv, _fs, ms, _) in segs:
        if pv < SHIM_BASE + 0x1000 and pv + ms > SHIM_BASE:
            raise SystemExit(f'guest overlaps shim at {hex(pv)}')
    phs = [struct.pack('<IIQQQQQQ', 1, 5, shim_off, SHIM_BASE, SHIM_BASE, len(sb), 0x1000, 0x1000)]
    payload = []
    cur = 0x2000
    for (po, pv, fs, ms, fl) in segs:
        cur = (cur + 0xfff) & ~0xfff
        phs.append(struct.pack('<IIQQQQQQ', 1, fl, cur, pv, pv, fs, ms, 0x1000))
        payload.append((cur, d[po:po + fs]))
        cur += fs
    eh = bytearray(b'\x7fELF' + bytes([2, 1, 1, 0]) + b'\x00' * 8)
    eh += struct.pack('<HHI', 2, 243, 1)
    eh += struct.pack('<QQQ', SHIM_BASE, 64, 0)
    eh += struct.pack('<IHHHHHH', 0, 64, 56, 1 + len(segs), 64, 0, 0)
    out = bytearray(eh) + b''.join(phs)
    if len(out) > shim_off:
        raise SystemExit('headers too large')
    out += b'\x00' * (shim_off - len(out))
    out += sb
    if len(out) < shim_off + 0x1000:
        out += b'\x00' * (shim_off + 0x1000 - len(out))
    for (fo, data) in payload:
        if fo > len(out):
            out += b'\x00' * (fo - len(out))
        end = fo + len(data)
        if end > len(out):
            out += b'\x00' * (end - len(out))
        out[fo:end] = data
    open(outpath, 'wb').write(bytes(out))


def _strip_ansi(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == '\x1b' and i + 1 < len(s) and s[i + 1] == '[':
            i += 2
            while i < len(s) and not ('A' <= s[i] <= 'Z' or 'a' <= s[i] <= 'z'):
                i += 1
            i += 1
            continue
        out.append(s[i])
        i += 1
    return ''.join(out)


def run(elfpath, timeout=2):
    tmpdir = os.path.dirname(os.path.abspath(elfpath)) or '.'
    combined = os.path.join(tmpdir, '.riscv64_combined.elf')
    outfile = os.path.join(tmpdir, '.riscv64_stdout.txt')
    combine(elfpath, combined)
    qemu = ['qemu-system-riscv64', '-M', 'virt', '-m', '256M', '-bios', 'none',
            '-serial', f'file:{outfile}', '-monitor', 'stdio',
            '-kernel', combined, '-no-reboot']
    p = subprocess.Popen(qemu, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True)
    time.sleep(timeout)
    p.stdin.write('xp /1gx 0x80000ff0\nquit\n')
    p.stdin.flush()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    mon = _strip_ansi(p.stdout.read())
    exit_code = -1
    for line in mon.splitlines():
        if '80000ff0:' in line.lower():
            val = line.split(':')[-1].strip().split()[0]
            exit_code = int(val, 16) & 0xff
            if exit_code == 0xff:
                exit_code = -1
            break
    stdout = ''
    if os.path.exists(outfile):
        stdout = open(outfile, 'rb').read().decode('utf-8', 'replace')
        os.unlink(outfile)
    try:
        os.unlink(combined)
    except OSError:
        pass
    return exit_code, stdout


if __name__ == '__main__':
    elf = sys.argv[1]
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    code, out = run(elf, timeout)
    sys.stdout.write(out)
    if out and not out.endswith('\n'):
        sys.stdout.write('\n')
    print(f'__EXIT_CODE__={code}', file=sys.stderr)
    sys.exit(0 if code == 0 else 1)
