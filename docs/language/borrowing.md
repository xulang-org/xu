# Borrowing and mutable bindings

This guide describes the compiler's current rules. The direction agreed in
[PR #34](https://github.com/xulang-org/xu/pull/34) is described separately below;
Phase B implements checked shared views of writable reference names. Its new
mutable spellings and ordinary-value automatic borrowing remain planned.

## Current syntax

Binding mutability controls whether a name can be reassigned. Borrow permission
controls whether the borrowed value can be written. These are independent.

| Form | Meaning |
| --- | --- |
| `x := value` / `let x: T = value` | Immutable binding |
| `mut x := value` | Mutable binding; later write `x = other` |
| `&T` / `&x` | Shared, read-only reference / borrow |
| `&mut T` / `mut &x` | Exclusive, writable reference / borrow |
| `mut s := &x` | Reassignable shared reference; cannot write through `s` |
| `r := mut &x` | Writable reference; `*r = value` does not require `mut r` |
| `mut r := mut &x` | Both binding and borrow permit writing |

Writable borrows normally require a mutable owner or a writable parent reference:

```xu
fn main() {
    mut x := 1
    r := mut &x
    *r = 2
    println(*r)
}
```

Making a shared reference binding mutable does not upgrade its permission:
`mut s := &x; *s = 2` fails. Obtain a writable borrow from the owner instead,
after conflicting borrows end. In expressions use `mut &x`; `&mut T` is the
type spelling, so `&mut x` is not a writable borrow expression.

## Reference slots and reborrows

`&r` borrows the reference slot itself (within the supported nesting limits).
`&*r` borrows the value reached through `r`. They are different operations.

| Operation | Current behavior |
| --- | --- |
| `&*r` with `r: &T` | Copies the shared reference, retaining its loan origin |
| `&*r` with `r: &mut T` | Creates a shared reborrow and freezes conflicting parent access |
| `mut &*r` with `r: &mut T` | Creates an exclusive child borrow |
| `mut &*r` with `r: &T` | Rejected; shared permission cannot be upgraded |
| `read(r)` expecting `&T`, with `r: &mut T` | Implicit shared reborrow, equivalent to `read(&*r)` |
| `write(r)` expecting `&mut T`, with `r: &mut T` | Synchronous argument passing already supports reborrowing |
| `q := r` with `r: &mut T` | Transfers the exclusive reference according to move rules |

Reborrowing an exclusive reference currently requires a local reference name.
For example, `&*holder.r` is restricted when `holder.r` is an exclusive reference.
The same boundary applies to implicit shared views: field, index, call, and
`mut &x` expressions cannot downgrade directly. Binding the reference to a local
first may move it; this is not an automatic,
semantics-preserving fix, and existing field move restrictions still apply.

## Last use and frozen parents

A shared view and its descendants keep their loan alive through their last use.
Conflicting writes, moves, and exclusive child borrows must wait until then:

```xu
fn read(v &int) int { << *v }

fn main() {
    mut x := 1
    r := mut &x
    let s: &int = r
    println(read(s))
    // A write through r before the preceding last use of s would fail.
    *r = 2
    println(*r)
}
```

Loan holders include aggregates, call results, and closure captures. Branches
can retain multiple possible origins. Analysis is conservative at statement
boundaries; loops and reference rebinding have additional restrictions.
Diagnostics identify the tracked start and last-use statements for conflicting
shared reborrows, including holders propagated through these paths.

Read-only method receivers have an existing special case: `r.read()` can coexist
with live shared descendants. An exclusive descendant still blocks it. Explicit
`&*r` currently has a stricter frozen-parent check; do not assume every receiver
operation is interchangeable with an explicit reborrow. New implicit shared
views follow the stricter explicit-reborrow rule, preserving this receiver case.

A shared expectation can appear in a synchronous function or function-value
argument, a method argument, a typed local, assignment, aggregate element or
field, or a return. It must have the identical direct pointee type. The local
keeps its writable type; the shared view does not move it. `q := r` without a
shared expectation still transfers the writable reference.

Temporary call loans also retain their parent reference. Calls such as
`both(r, r)` with shared and writable parameters, or `both(&*r, r)`, are rejected
in either argument order. A nested scalar read can finish before a writable
argument is used; a nested reference result keeps its loan. Results and stored
views continue to freeze the parent through the holder's last use. No recursive
array or nested-reference conversion is added.

## Other boundaries

Supported field and index borrows retain their existing place restrictions.
An element loan can prevent changing the container's structure (for example,
growing a slice) while that loan is live. A borrow cannot outlive its owner.
Closure capture preserves borrow permission and lifetime constraints. References
cannot cross `xu` coroutine or channel boundaries where the compiler rejects
them today; synchronous reborrowing does not grant permission to escape.

Dynamic boxes (`temp`, `any`, and dynamic interfaces) have special existing
rules: shared borrowing is restricted, and some exclusive borrows used for
`is` / `as` do not require a mutable binding. These are not general permission
upgrades. Xu uses ownership inference, custom AOT backends, and zero GC; these
checks do not introduce runtime borrow objects or a garbage collector.

## Planned direction, not current syntax

Phase A improves diagnostics and adds this guide without changing legal programs.
Phase B lets an exclusive reference name `r` satisfy a shared `&T` expectation
by inserting a checked shared reborrow. Phase C is planned to
add the new mutable spellings and automatic read-only borrowing from ordinary
places under a known shared expectation.

| Intent | Planned form | Write today |
| --- | --- | --- |
| Mutable binding | `$x := value` / `let $x: T = value` | `mut x := value` (inferred type) |
| Writable borrow / reference type | `$&x` / `$&T` | `mut &x` / `&mut T` |
| Read-only use under a shared expectation | `read(x)` / `read(r)` | `read(&x)` for ordinary values; `read(r)` for reference names |
| Explicit reborrow of an existing reference | `&*r`, permission from expectation | `&*r` for shared; `mut &*r` for exclusive |

The intended daily rule is to write the reference name `r`; use `&*r` when an
explicit reborrow is needed. With `$r := $&x`, the left `$` marks the binding and
the right `$&` marks borrow permission. After declaration, uses still write `r`
or `*r = value`, without repeating `$`.

`&$`, `$&*r`, and `*$&r` are rejected spellings, not migration alternatives.
`$&x := value` confuses borrowing with a binding declaration; the planned binding
form is `$x := value`. A bare `$T` is not a reference type. `~` stays unused,
and `pub` is unchanged. Existing `$linux` compilation tags and `$name` string
interpolation keep their meanings.

The planned expression omission does not reinterpret type `T` as `&T`, infer
arbitrary borrowing without an expectation, upgrade shared permissions, relax
escape rules, or remove current place restrictions. Old spellings remain legal
in Phase B; syntax migration and ordinary-value automatic borrowing are not
implemented here.
