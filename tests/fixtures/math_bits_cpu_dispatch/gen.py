"""Independent u64 model; no SWAR or emitter-specific instruction logic."""
from pathlib import Path

MASK = (1 << 64) - 1


def signed(x):
    x &= MASK
    return x if x < (1 << 63) else x - (1 << 64)


def reverse_bytes(x):
    return int.from_bytes((x & MASK).to_bytes(8, 'little'), 'big')


def rotate(x, k):
    x &= MASK
    k %= 64
    return ((x << k) | (x >> ((64 - k) % 64))) & MASK


def mix(x):
    x = signed(x)
    r = (x & MASK).bit_count() + 64
    r ^= reverse_bytes(x)
    r = signed(r + rotate(x, -65))
    r ^= rotate(x, 64)
    r = signed(r + rotate(x, -1))
    r ^= rotate(x, 0)
    r = signed(r + rotate(x, 7))
    r ^= rotate(x, -32)
    r = signed(r + rotate(x, 63))
    r ^= rotate(x, -64)
    r = signed(r + rotate(x, 129))
    if x < 0:
        r ^= ((x ^ r) & MASK).bit_count()
    else:
        r = signed(r + ((x + r) & MASK).bit_count())
    return signed(r ^ reverse_bytes(r))


if __name__ == '__main__':
    values = [0, 1, -1, (1 << 63) - 1, -(1 << 63),
              0x0123456789abcdef, 0x5555555555555555, 0xaaaaaaaaaaaaaaaa]
    seed = 7
    for _ in range(96):
        seed = signed(seed * 6364136223846793005 + 1442695040888963407)
        values.append(seed)
    results = [mix(x) for x in values] + [64, 0, signed(reverse_bytes(0x0123456789abcdef))]
    Path(__file__).with_name('expected.txt').write_text(''.join(f'{x}\n' for x in results))
