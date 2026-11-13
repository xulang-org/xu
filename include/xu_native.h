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

/* xu-c-2 borrowed i64 spans: one pointer argument to a 16-byte descriptor.
 * These are synchronous, call-scoped views, never owning values. Native code
 * must not retain the descriptor or data pointer after returning, resize the
 * Xu array, or modify descriptor fields. Mutable spans allow element writes
 * only; read-only spans also prohibit writing through aliases to the data.
 * A zero-length span may have a null data pointer. Lengths count 8-byte ints.
 * Keep this stable layout independent of the compiler's private descriptors.
 * xu-c-2 also supports xu-c-1 scalar arguments/results (int, bool, f64,
 * i32, u32, u8 and a void result). Spans remain argument-only.
 */
typedef struct { xu_int len; const xu_int *data; } xu_i64_span;
typedef struct { xu_int len; xu_int *data; } xu_i64_span_mut;
/* Byte spans have the same descriptor layout, with one-byte elements. */
typedef struct { xu_int len; const unsigned char *data; } xu_u8_span;
typedef struct { xu_int len; unsigned char *data; } xu_u8_span_mut;

#if defined(__cplusplus)
static_assert(sizeof(xu_int) == 8, "Xu integers require 64 bits");
#if defined(__SIZEOF_POINTER__) && __SIZEOF_POINTER__ == 8
static_assert(sizeof(xu_i64_span) == 16, "xu-c-2 descriptor size mismatch");
static_assert(sizeof(xu_u8_span) == 16, "xu-c-2 byte descriptor size mismatch");
#endif
#else
_Static_assert(sizeof(xu_int) == 8, "Xu integers require 64 bits");
#if defined(__SIZEOF_POINTER__) && __SIZEOF_POINTER__ == 8
_Static_assert(sizeof(xu_i64_span) == 16, "xu-c-2 descriptor size mismatch");
_Static_assert(sizeof(xu_u8_span) == 16, "xu-c-2 byte descriptor size mismatch");
#endif
#endif

#endif /* XU_NATIVE_H */
