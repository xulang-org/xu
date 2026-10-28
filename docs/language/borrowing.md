# Bindings and borrows

A mutable binding and a writable borrow grant different permissions:

```xu
mut x := 1        // x can be reassigned
r := mut &x       // r can write x; r itself cannot be reassigned
*r = 2
```

`mut r := &x` allows rebinding `r`; it does not allow `*r = 2`.
A shared reference (`&T`) grants read access. A writable reference (`&mut T`)
grants exclusive write access. A shared reference cannot be upgraded to writable;
borrow from the owner after conflicting borrows end.

`&r` borrows the reference's slot. `&*r` explicitly reborrows its pointee.
Currently, passing a writable reference to a shared parameter requires `read(&*r)`.
A shared reborrow freezes its writable parent through the last use of the shared
view and its descendants. Put conflicting writes and exclusive reborrows after
that last use. Diagnostics identify the creation and last-use statements when
this shared descendant causes the conflict. Loan analysis uses statement-level
last uses and conservatively joins possible sources across branches.

Reborrowing a writable reference currently requires a local reference name.
For a field or index source, extracting a local may move that reference; it is
not an automatic fix. Existing field and element loan, closure capture, lifetime,
and coroutine escape restrictions still apply. Read-only method receivers retain
their existing allowance for shared descendants; explicit `&*r` has a stricter
frozen-parent check. Existing dynamic-box exceptions are unchanged.

The planned spellings are `$name :=` for mutable bindings, `$&x` for writable
borrows from a place, and `$&T` for writable reference types. This compiler does
not yet accept them. Continue using `mut name :=`, `mut &x`, and `&mut T`.
`&$`, `$&*r`, and `*$&r` are rejected spellings. Explicit reborrowing uses `&*r`;
the planned daily read reborrow is plain `r` once implicit downgrade is supported.
`pub` still controls visibility. File tags such as `$linux` and string
interpolation retain their existing meaning.

Implicit downgrade remains deferred. Before enabling it, temporary reborrows need
parent identities so that shared and writable arguments conflict in either
argument order, including nested expressions. The baseline currently accepts
`both(&*p, p)` for shared and writable parameters of the same pointee. Reusing
that path alone would not satisfy the downgrade's safety requirements. This
phase preserves acceptance and does not fix that existing same-expression gap.
