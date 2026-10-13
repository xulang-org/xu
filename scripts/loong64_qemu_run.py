#!/usr/bin/env python3
"""loong64 QEMU runner: wrap a linux-loongarch64 static ELF with a minimal
semihosting shim (EENTRY handler + FPU enable + mmap/write/exit trap emulation)
and run it under qemu-system-loongarch64 -M virt -kernel.

Usage: loong64_qemu_run.py <a.out> [timeout_seconds]

stdout: the guest's write() syscalls are emitted to the loongarch virt UART
(NS16550 @ 0x1fe001e0) and captured here. exit code: the shim stores the
exit_group/exit code in a magic word @ 0x2fff0 and the runner reads it via the
QEMU monitor (`xp /1gx 0x2fff0`); the value is -1 until the program exits.
"""
import struct, subprocess, sys, os, time

# ---- LoongArch64 mini-encoder (encodings verified against QEMU 11.0.2) ----
def r3(op, rd, rj, rk): return op | ((rk & 31) << 10) | ((rj & 31) << 5) | (rd & 31)
def r2i(op, rd, rj, imm): return op | ((imm & 0xfff) << 10) | ((rj & 31) << 5) | (rd & 31)
def shi(op, rd, rj, ui6): return op | ((ui6 & 0x3f) << 10) | ((rj & 31) << 5) | (rd & 31)
def pcaddu12i(rd, si20): return 0x1c000000 | ((si20 & 0xfffff) << 5) | (rd & 31)

zero, ra, tp, sp, a0, a1, a2, a3, a4, a5, a6, a7 = 0,1,2,3,4,5,6,7,8,9,10,11
t0, t1, t2, t3, t4, t5, t6, t7, t8 = 12,13,14,15,16,17,18,19,20

SHIM_BASE = 0x300000   # shim lives in low RAM (below the 0x401000 code segment)
UART_BASE = 0x1fe001e0 # loongarch virt NS16550 #0 (regshift=0: THR@0, LSR@5)
EXIT_ADDR = 0x2fff0    # magic word: shim writes exit code here
BUMP_ADDR = 0x2fff8    # mmap bump cursor
BUMP_START = 0x5000000 # mmap arena base (low RAM)
FILE_LEN_ADDR = 0x2fe0
FILE_POS_ADDR = 0x2fe8
FILE_BUF = 0x6000000
CLONE_FLAG = 0x2df0
CTX_BASE = 0x2c00  # [0]=ERA, [8*i]=r_i for i=1..31

def build_shim(entry):
    labels, code, pending = {}, [], []
    def emit(w): code.append(w)
    def L(n): labels[n] = len(code)
    def br16(b, rj, rd, l): pending.append((len(code), 'b16', b, rj, rd, l)); emit(0)
    def br21(b, rj, l): pending.append((len(code), 'b21', b, rj, 0, l)); emit(0)
    def br26(b, l): pending.append((len(code), 'b26', b, 0, 0, l)); emit(0)
    def lea(rd, l): pending.append((len(code), 'pcaddi', 0, 0, rd, l)); emit(0); emit(0)

    L('start')
    lea(t0, 'handler')
    emit(0x04000020 | (12 << 10) | (t0 & 31))          # csrwr t0, 12 (EENTRY = handler)
    emit(0x04000000 | (2 << 10) | (t0 & 31))           # csrrd t0, 2 (EUEN)
    emit(r2i(0x03800000, t0, t0, 1))                   # ori t0, t0, 1 (FPE = enable FPU)
    emit(0x04000020 | (2 << 10) | (t0 & 31))           # csrwr t0, 2
    emit(0x14000000 | ((0x800 & 0xfffff) << 5) | (sp & 31))  # lu12i.w sp, 0x800 -> 0x800000
    for off in (0, 8, 16, 24, 32, 40):                 # argc/argv/envp/auxv = 0
        emit(r2i(0x29c00000, zero, sp, off))           # st.d zero, sp, off
    # exit-code word = sentinel -1
    emit(0x14000000 | ((0x2f & 0xfffff) << 5) | (t6 & 31))
    emit(r2i(0x03800000, t6, t6, 0xff0))               # t6 = 0x2fff0
    emit(r2i(0x02c00000, t7, zero, -1))                # t7 = -1
    emit(r2i(0x29c00000, t7, t6, 0))                   # [0x2fff0] = -1
    # mmap bump cursor = BUMP_START
    emit(0x14000000 | ((0x2f & 0xfffff) << 5) | (t6 & 31))
    emit(r2i(0x03800000, t6, t6, 0xff8))               # t6 = 0x2fff8
    emit(0x14000000 | ((0x500 & 0xfffff) << 5) | (t7 & 31))
    emit(r2i(0x03800000, t7, t7, 0))                   # t7 = 0x5000000
    emit(r2i(0x29c00000, t7, t6, 0))                   # [0x2fff8] = 0x5000000
    # ramdisk meta: len=0, pos=0
    emit(0x14000000 | ((0x2f & 0xfffff) << 5) | (t6 & 31))
    emit(r2i(0x03800000, t6, t6, 0xe0))                # t6 = 0x2fe0
    emit(r2i(0x29c00000, zero, t6, 0))
    emit(r2i(0x03800000, t6, t6, 8))                   # t6 = 0x2fe8
    emit(r2i(0x29c00000, zero, t6, 0))
    # clone flag = 0
    emit(0x14000000 | ((0x2d & 0xfffff) << 5) | (t6 & 31))
    emit(r2i(0x03800000, t6, t6, 0xf0))                # t6 = 0x2df0
    emit(r2i(0x29c00000, zero, t6, 0))
    # jump to the target ELF entry
    emit(0x14000000 | (((entry >> 12) & 0xfffff) << 5) | (t1 & 31))
    emit(r2i(0x03800000, t1, t1, entry & 0xfff))
    emit(0x4c000000 | ((t1 & 31) << 5) | (zero & 31))  # jirl zero, t1, 0

    L('handler')
    # Park t7/t8; skip CTX snapshot while sync-cloned child is running.
    emit(r2i(0x29c00000, t7, sp, -8))
    emit(r2i(0x29c00000, t8, sp, -16))
    emit(0x14000000 | ((0x2d & 0xfffff) << 5) | (t7 & 31))
    emit(r2i(0x03800000, t7, t7, 0xf0))
    emit(r2i(0x28c00000, t8, t7, 0))
    br21(0x44000000, t8, 'dispatch')  # bnez → child, skip save
    emit(r2i(0x29c00000, t6, sp, -24))
    emit(0x14000000 | ((0x2c & 0xfffff) << 5) | (t7 & 31))
    emit(r2i(0x03800000, t7, t7, 0))   # t7 = CTX_BASE
    emit(0x04000000 | (6 << 10) | (t8 & 31))  # csrrd t8, ERA
    emit(r2i(0x29c00000, t8, t7, 0))
    for ri in range(1, 32):
        if ri in (t6, t7, t8):
            continue
        emit(r2i(0x29c00000, ri, t7, ri * 8))
    emit(r2i(0x28c00000, t8, sp, -8))   # orig t7
    emit(r2i(0x29c00000, t8, t7, t7 * 8))
    emit(r2i(0x28c00000, t8, sp, -16))  # orig t8
    emit(r2i(0x29c00000, t8, t7, t8 * 8))
    emit(r2i(0x28c00000, t8, sp, -24))  # orig t6
    emit(r2i(0x29c00000, t8, t7, t6 * 8))

    L('dispatch')
    emit(r2i(0x02c00000, t8, zero, 222)); br16(0x58000000, a7, t8, 'do_mmap')
    emit(r2i(0x02c00000, t8, zero, 64));  br16(0x58000000, a7, t8, 'do_write')
    emit(r2i(0x02c00000, t8, zero, 63));  br16(0x58000000, a7, t8, 'do_read')
    emit(r2i(0x02c00000, t8, zero, 56));  br16(0x58000000, a7, t8, 'do_openat')
    emit(r2i(0x02c00000, t8, zero, 57));  br16(0x58000000, a7, t8, 'do_close')
    emit(r2i(0x02c00000, t8, zero, 220)); br16(0x58000000, a7, t8, 'do_clone')
    emit(r2i(0x02c00000, t8, zero, 98));  br16(0x58000000, a7, t8, 'do_futex')
    emit(r2i(0x02c00000, t8, zero, 93));  br16(0x58000000, a7, t8, 'do_exit_thread')
    emit(r2i(0x02c00000, t8, zero, 94));  br16(0x58000000, a7, t8, 'do_exit_group')
    emit(r3(0x00150000, a0, zero, zero)); br26(0x50000000, 'return_')

    L('do_mmap')                                        # mmap(addr,len,prot,flags,fd,off) -> bump
    emit(r2i(0x02c00000, t8, a1, -1))                   # len-1
    emit(shi(0x00450000, t8, t8, 12))                   # (len-1)>>12
    emit(r2i(0x02c00000, t8, t8, 1))                    # +1 = ceil(len/4096)
    emit(shi(0x00410000, t8, t8, 12))                   # <<12 = page-aligned
    emit(0x14000000 | ((0x2f & 0xfffff) << 5) | (t6 & 31))
    emit(r2i(0x03800000, t6, t6, 0xff8))                # t6 = bump cursor addr
    emit(r2i(0x28c00000, t7, t6, 0))                    # t7 = cursor
    emit(r3(0x00150000, a0, zero, t7))                  # a0 = cursor (ret)
    emit(r3(0x00108000, t7, t7, t8))                    # cursor += len
    emit(r2i(0x29c00000, t7, t6, 0))                    # store cursor
    br26(0x50000000, 'return_')

    L('do_openat')                                      # -> fd 3; O_TRUNC clears
    emit(r2i(0x03400000, t8, a2, 0x200))                # andi flags, O_TRUNC
    br21(0x40000000, t8, 'open_keep')                   # beqz
    emit(0x14000000 | ((0x2f & 0xfffff) << 5) | (t6 & 31))
    emit(r2i(0x03800000, t6, t6, 0xe0))
    emit(r2i(0x29c00000, zero, t6, 0))
    L('open_keep')
    emit(0x14000000 | ((0x2f & 0xfffff) << 5) | (t6 & 31))
    emit(r2i(0x03800000, t6, t6, 0xe8))
    emit(r2i(0x29c00000, zero, t6, 0))
    emit(r2i(0x02c00000, a0, zero, 3))
    br26(0x50000000, 'return_')

    L('do_close')
    emit(r3(0x00150000, a0, zero, zero))
    br26(0x50000000, 'return_')

    L('do_write')
    emit(r2i(0x02c00000, t8, zero, 3)); br16(0x58000000, a0, t8, 'file_write')
    # stdout/stderr -> UART
    emit(0x14000000 | ((0x1fe00 & 0xfffff) << 5) | (t6 & 31))
    emit(r2i(0x03800000, t6, t6, 0x1e0))                # t6 = UART base
    emit(r3(0x00150000, t7, zero, a2))                  # t7 = len
    emit(r3(0x00150000, t8, zero, a1))                  # t8 = ptr
    L('wloop')
    br21(0x40000000, t7, 'wdone')                       # while len != 0
    emit(r2i(0x2a000000, t5, t6, 5))                    # t5 = LSR
    emit(r2i(0x03400000, t5, t5, 0x20))                 # THRE (bit 5)
    br21(0x40000000, t5, 'wloop')                       # busy-wait
    emit(r2i(0x2a000000, t4, t8, 0))                    # byte = *ptr
    emit(r2i(0x29000000, t4, t6, 0))                    # THR = byte
    emit(r2i(0x02c00000, t8, t8, 1)); emit(r2i(0x02c00000, t7, t7, -1))
    br26(0x50000000, 'wloop')
    L('wdone')
    emit(r3(0x00150000, a0, zero, a2))                  # ret = len
    br26(0x50000000, 'return_')

    L('file_write')
    emit(0x14000000 | ((0x2f & 0xfffff) << 5) | (t6 & 31))
    emit(r2i(0x03800000, t6, t6, 0xe0))                 # t6 = FILE_LEN addr
    emit(r2i(0x28c00000, t7, t6, 0))                    # t7 = len
    emit(0x14000000 | ((0x600 & 0xfffff) << 5) | (t8 & 31))
    emit(r2i(0x03800000, t8, t8, 0))                   # t8 = FILE_BUF
    emit(r3(0x00108000, t8, t8, t7))                    # dst = buf+len
    emit(r3(0x00150000, a3, zero, a1))                  # src
    emit(r3(0x00150000, a4, zero, a2))                  # n
    L('fwloop')
    br21(0x40000000, a4, 'fwdone')
    emit(r2i(0x2a000000, t5, a3, 0))
    emit(r2i(0x29000000, t5, t8, 0))
    emit(r2i(0x02c00000, a3, a3, 1))
    emit(r2i(0x02c00000, t8, t8, 1))
    emit(r2i(0x02c00000, a4, a4, -1))
    br26(0x50000000, 'fwloop')
    L('fwdone')
    emit(r3(0x00108000, t7, t7, a2))
    emit(r2i(0x29c00000, t7, t6, 0))
    emit(r3(0x00150000, a0, zero, a2))
    br26(0x50000000, 'return_')

    L('do_read')
    emit(r2i(0x02c00000, t8, zero, 3)); br16(0x5c000000, a0, t8, 'read_bad')  # bne a0,3
    emit(0x14000000 | ((0x2f & 0xfffff) << 5) | (t6 & 31))
    emit(r2i(0x03800000, t6, t6, 0xe0))
    emit(r2i(0x28c00000, t7, t6, 0))                    # len
    emit(0x14000000 | ((0x2f & 0xfffff) << 5) | (t6 & 31))
    emit(r2i(0x03800000, t6, t6, 0xe8))
    emit(r2i(0x28c00000, t8, t6, 0))                    # pos (t6 still pos addr)
    emit(r3(0x00118000, t5, t7, t8))                    # rem = len - pos
    br21(0x40000000, t5, 'read_eof')
    emit(r3(0x00120000, t4, a2, t5))                    # slt t4 = (a2 < rem)
    br21(0x44000000, t4, 'read_use_a2')                  # bnez -> use a2
    emit(r3(0x00150000, a5, zero, t5))                  # n = rem
    br26(0x50000000, 'read_copy')
    L('read_use_a2')
    emit(r3(0x00150000, a5, zero, a2))
    L('read_copy')
    emit(0x14000000 | ((0x600 & 0xfffff) << 5) | (t7 & 31))
    emit(r2i(0x03800000, t7, t7, 0))
    emit(r3(0x00108000, t7, t7, t8))                    # src = buf+pos
    emit(r3(0x00150000, a3, zero, a1))
    emit(r3(0x00150000, a4, zero, a5))
    L('frloop')
    br21(0x40000000, a4, 'frdone')
    emit(r2i(0x2a000000, t5, t7, 0))
    emit(r2i(0x29000000, t5, a3, 0))
    emit(r2i(0x02c00000, t7, t7, 1))
    emit(r2i(0x02c00000, a3, a3, 1))
    emit(r2i(0x02c00000, a4, a4, -1))
    br26(0x50000000, 'frloop')
    L('frdone')
    emit(r3(0x00108000, t8, t8, a5))
    emit(r2i(0x29c00000, t8, t6, 0))                    # store pos
    emit(r3(0x00150000, a0, zero, a5))
    br26(0x50000000, 'return_')
    L('read_eof')
    emit(r3(0x00150000, a0, zero, zero))
    br26(0x50000000, 'return_')
    L('read_bad')
    emit(r2i(0x02c00000, a0, zero, -9))
    br26(0x50000000, 'return_')

    L('do_futex')
    emit(r3(0x00150000, a0, zero, zero))
    br26(0x50000000, 'return_')

    L('do_clone')
    emit(0x14000000 | ((0x2c & 0xfffff) << 5) | (t7 & 31))
    emit(r2i(0x03800000, t7, t7, 0))
    emit(r2i(0x28c00000, sp, t7, a1 * 8))  # sp = saved a1
    emit(0x14000000 | ((0x2d & 0xfffff) << 5) | (t7 & 31))
    emit(r2i(0x03800000, t7, t7, 0xf0))
    emit(r2i(0x02c00000, t8, zero, 1))
    emit(r2i(0x29c00000, t8, t7, 0))
    emit(r3(0x00150000, a0, zero, zero))
    br26(0x50000000, 'return_')

    L('do_exit_thread')
    emit(0x14000000 | ((0x2d & 0xfffff) << 5) | (t7 & 31))
    emit(r2i(0x03800000, t7, t7, 0xf0))
    emit(r2i(0x28c00000, t8, t7, 0))
    br21(0x40000000, t8, 'do_exit_group')  # beqz → no parent
    emit(r2i(0x29c00000, zero, t7, 0))
    emit(0x14000000 | ((0x2c & 0xfffff) << 5) | (t7 & 31))
    emit(r2i(0x03800000, t7, t7, 0))
    emit(r2i(0x28c00000, t8, t7, 0))       # ERA
    emit(r2i(0x02c00000, t8, t8, 4))
    for ri in range(1, 32):
        if ri in (a0, t7, t8):
            continue
        emit(r2i(0x28c00000, ri, t7, ri * 8))
    emit(r2i(0x02c00000, a0, zero, 2))
    emit(0x04000020 | (6 << 10) | (t8 & 31))  # csrwr ERA
    emit(0x06483800)  # ertn

    L('do_exit_group')
    emit(0x14000000 | ((0x2f & 0xfffff) << 5) | (t6 & 31))
    emit(r2i(0x03800000, t6, t6, 0xff0))
    emit(r2i(0x29c00000, a0, t6, 0))
    br26(0x50000000, 'do_exit_group')

    L('return_')
    emit(0x04000000 | (6 << 10) | (t8 & 31))
    emit(r2i(0x02c00000, t8, t8, 4))
    emit(0x04000020 | (6 << 10) | (t8 & 31))
    emit(0x06483800)

    for i, kind, b, rj, rd, l in pending:
        offs = labels[l] - i
        if kind == 'b16':   code[i] = b | ((offs & 0xffff) << 10) | ((rj & 31) << 5) | (rd & 31)
        elif kind == 'b21': code[i] = b | ((offs & 0xffff) << 10) | ((offs >> 16) & 0x1f) | ((rj & 31) << 5)
        elif kind == 'b26': code[i] = b | ((offs & 0xffff) << 10) | ((offs >> 16) & 0x3ff)
        elif kind == 'pcaddi':
            tgt = SHIM_BASE + labels[l] * 4; pc = SHIM_BASE + i * 4
            d = tgt - pc; lo = d & 0xfff
            if lo >= 0x800: lo -= 0x1000
            hi = (d - lo) >> 12
            code[i] = pcaddu12i(rd, hi)
            code[i + 1] = 0x02c00000 | ((lo & 0xfff) << 10) | ((rd & 31) << 5) | (rd & 31)
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
        po, pv, pp, fs, ms, al = struct.unpack_from('<QQQQQQ', d, off + 8)
        if t == 1:  # PT_LOAD
            segs.append((po, pv, fs, ms, fl))
    return entry, segs, d

def combine(elfpath, outpath):
    entry, segs, d = read_elf(elfpath)
    sb = build_shim(entry)
    shim_vaddr, shim_off = SHIM_BASE, 0x1000
    phs = [struct.pack('<IIQQQQQQ', 1, 5, shim_off, shim_vaddr, shim_vaddr, len(sb), len(sb), 0x1000)]
    payload = []
    cur_off = 0x2000
    for (po, pv, fs, ms, fl) in segs:
        cur_off = (cur_off + 0xfff) & ~0xfff
        phs.append(struct.pack('<IIQQQQQQ', 1, fl, cur_off, pv, pv, fs, ms, 0x1000))
        payload.append((cur_off, d[po:po + fs]))
        cur_off += fs
    eh = bytearray(b'\x7fELF' + bytes([2, 1, 1, 0]) + b'\x00' * 8)
    eh += struct.pack('<HHI', 2, 258, 1) + struct.pack('<Q', shim_vaddr) + struct.pack('<Q', 64) + struct.pack('<Q', 0)
    eh += struct.pack('<I', 0) + struct.pack('<H', 64) + struct.pack('<H', 56) + struct.pack('<H', 1 + len(segs)) \
        + struct.pack('<H', 64) + struct.pack('<H', 0) + struct.pack('<H', 0)
    out = bytearray(eh) + b''.join(phs)
    out += b'\x00' * (shim_off - len(out)) + sb
    for (fo, data) in payload:
        out += b'\x00' * (fo - len(out)) + data
    open(outpath, 'wb').write(bytes(out))
    return outpath

def run(elfpath, timeout=10):
    tmpdir = os.path.dirname(os.path.abspath(elfpath)) or '.'
    combined = os.path.join(tmpdir, '.loong64_combined.elf')
    outfile = os.path.join(tmpdir, '.loong64_stdout.txt')
    combine(elfpath, combined)
    # serial (guest UART) -> outfile; monitor -> stdio for exit-code read.
    qemu = ['qemu-system-loongarch64', '-M', 'virt',
            '-serial', f'file:{outfile}', '-monitor', 'stdio',
            '-kernel', combined, '-no-reboot']
    p = subprocess.Popen(qemu, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True)
    time.sleep(timeout)
    # read the shim's magic exit-code word, then quit (monitor replies are
    # echoed with ANSI line-edit sequences, so parse the result line below).
    p.stdin.write('xp /1gx 0x2fff0\nquit\n'); p.stdin.flush()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill(); p.wait()
    mon = p.stdout.read()
    exit_code = -1
    for line in mon.splitlines():
        if '0002fff0:' in line:
            val = line.split(':')[-1].strip()
            exit_code = int(val, 16) & 0xff  # low 8 bits = exit code
            if exit_code == 0xff:
                exit_code = -1  # sentinel: program never reached exit
            break
    stdout = open(outfile, 'rb').read().decode('utf-8', 'replace') if os.path.exists(outfile) else ''
    os.unlink(outfile); os.unlink(combined)
    return exit_code, stdout

if __name__ == '__main__':
    elf = sys.argv[1]
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    code, out = run(elf, timeout)
    sys.stdout.write(out)
    sys.stdout.flush()
    # report exit code to stderr so stdout stays clean
    sys.stderr.write(f'__EXIT_CODE__={code}\n')
    sys.stderr.flush()
