#ifndef XU_NATIVE_H
#define XU_NATIVE_H

/*
 * XUOBJ export labels use a leading `_xu_` on every target. Mach-O adds its
 * own leading underscore to C symbols, while ELF/COFF do not, so bridges use
 * this macro when declaring an exported C entry point.
 */
#if defined(__APPLE__)
#define XU_NATIVE_SYMBOL(name) name
#else
#define XU_NATIVE_SYMBOL(name) _##name
#endif

/* Header-only 64-bit Xu scalar; avoids requiring a target libc just to build
 * a small cross-platform bridge. It is ABI-equivalent to Xu `int`. */
typedef signed long long xu_int;
typedef unsigned long long xu_uint;

#endif /* XU_NATIVE_H */
