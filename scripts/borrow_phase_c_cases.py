"""Phase C spelling, expected-borrow and provenance regressions for P1."""


def check_phase_c(fixture):
    fixture('spec34_C_spellings', '''fn write(p $&int) { *p = 7 }
fn main() {
 $x := 1
 x = 2
 r := $&x
 write(r)
 println(*r)
 let w: $&int = &*r
 *w = 8
 println(*w)
 println(*r)
 let $n: int = 3
 n = 4
 println(n)
 $q := $&n
 *q = 5
 println(*q)
 q = $&x
 *q = 9
 println(*q)
 let $s: &int = n
 println(*s)
 s = x
 println(*s)
}''', output='7\n8\n8\n4\n5\n9\n5\n9\n')
    fixture('spec34_C_lifetime', '''fn identity(p $&a int) $&a int { << p }
fn main() { $x := 2
 r := identity($&x)
 *r = 6
 println(*r) }''', output='6\n')
    fixture('spec34_C_type_entries', '''struct Holder { r $&int }
struct Box#T { value T }
struct@ Writer { fn write() $&int }
fn identity(p $&int) $&int { << p }
fn (h &Holder) read() int { << *h.r }
fn main() { $x := 1
 let g: fn($&int) $&int = identity
 h := Holder{r: g($&x)}
 println(h.read())
 $y := 3
 b := Box#$&int{value: g($&y)}
 println(*b.value) }''', output='1\n3\n')
    fixture('spec34_C_receivers', '''struct Item { value int }
fn (p &Item) read() int { << p.value }
fn (p $&Item) write() { p.value = 9 }
fn main() { $x := Item{value: 3}
 println(x.read())
 p := $&x
 s := &p.value
 println(p.read())
 println(*s)
 p.write()
 println(p.read()) }''', output='3\n3\n3\n9\n')
    for spelling in ('r', '&*r'):
        fixture('spec34_C_daily_write_' + str(len(spelling)),
                'fn write(p $&int) { *p = 8 }\nfn main() { $x := 1\n r := $&x\n write(' + spelling + ')\n println(*r) }',
                output='8\n')
    for tag, arg in (('implicit', 'x'), ('explicit', '&x')):
        fixture('spec34_C_F25_' + tag,
                'fn read(p &int) int { << *p }\nfn main() { $x := 3\n println(read(' + arg + '))\n x = 4\n println(x) }',
                output='3\n4\n')
    fixture('spec34_C_F25_places', '''struct Item { text string, value int }
fn read(p &int) int { << *p }
fn text(p &string) string { << *p + "!" }
fn item(p &Item) int { << p.value }
fn slice(p &[]int) int { << p[1] }
fn main() {
 x := Item{text: "xu", value: 3}
 println(item(x))
 println(text(x.text))
 println(read(x.value))
 xs := [4, 5]
 println(slice(xs))
 println(read(xs[1]))
 items := [Item{text: "buffer", value: 6}]
 println(text(items[0].text))
 println(read(items[0].value))
 strings := ["hello"]
 println(text(strings[0]))
}''', output='3\nxu!\n3\n5\n5\nbuffer!\n6\nhello!\n')
    fixture('spec34_C_F25_fnval_generic_method', '''struct Item { value int }
fn read(p &int) int { << *p }
fn generic#T(seed T, p &int) int { << 5 }
fn (p &Item) add(q &int) int { << p.value + *q }
fn main() { x := 3
 f := read
 println(f(x))
 println(generic(true, x))
 y := Item{value: 4}
 println(y.add(x)) }''', output='3\n5\n7\n')
    fixture('spec34_C_D16_storage', '''struct View { r &int }
fn view(p &int) &int { << p }
fn main() { $x := 2
 let s: &int = x
 println(*s)
 y := 3
 let $q: &int = y
 q = x
 h := View{r: q}
 println(*h.r)
 call := view(x)
 println(*call)
 xs := [2]&int{x, y}
 println(*xs[0])
 x = 4
 println(x) }''', output='2\n2\n2\n2\n4\n')
    fixture('spec34_C_no_expectation_value', 'fn main() { $x := 1\n y := x\n x = 2\n println(y)\n println(x) }', output='1\n2\n')
    fixture('spec34_C_no_expectation_move', 'fn main() { $x := 1\n p := $&x\n q := p\n println(*p)\n println(*q) }', 'use of moved value')
    fixture('spec34_C_no_automatic_writable', 'fn write(p $&int) {}\nfn main() { $x := 1\n write(x) }', 'type mismatch: expected &mut int, found int')
    fixture('spec34_C_shared_binding_permission', 'fn main() { x := 1\n let $s: &int = x\n *s = 2 }', 'cannot assign through shared reference')
    fixture('spec34_C_immutable_owner', 'fn main() { x := 1\n r := $&x }', 'cannot mutably borrow immutable variable')
    fixture('spec34_C_shared_upgrade', 'fn write(p $&int) {}\nfn bad(s &int) { write(&*s) }\nfn main() {}', 'cannot obtain an exclusive writable borrow from a shared reference')
    fixture('spec34_C_explicit_write_freeze', 'fn bad(r $&int) { let q: $&int = &*r\n println(*r)\n println(*q) }\nfn main() {}', 'mutably borrowed')
    fixture('spec34_C_shared_blocks_write_reborrow', 'fn bad(r $&int) { let s: &int = r\n let q: $&int = &*r\n println(*s)\n println(*q) }\nfn main() {}', 'frozen reference')
    for tag, body in (
        ('let', 'let s: &int = x\n x = 2\n println(*s)'),
        ('call_result', 's := view(x)\n x = 2\n println(*s)'),
        ('aggregate', 'h := View{r: x}\n x = 2\n println(*h.r)'),
        ('closure', 'let s: &int = x\n f := fn() int { << *s }\n x = 2\n println(f())'),
        ('branch', 'let $s: &int = y\n if flag { s = x }\n x = 2\n println(*s)'),
    ):
        fixture('spec34_C_F25_held_' + tag,
                'struct View { r &int }\nfn view(p &int) &int { << p }\nfn bad(flag bool) { $x := 1\n y := 3\n ' + body + '\n}\nfn main() {}',
                'because it is borrowed')
    for tag, call in (('shared_first', 'both(x, $&x)'), ('writable_first', 'reverse($&x, x)'),
                      ('nested_result', 'both(view(x), $&x)')):
        fixture('spec34_C_F25_temporary_' + tag,
                'fn both(s &int, w $&int) {}\nfn reverse(w $&int, s &int) {}\nfn view(s &int) &int { << s }\nfn main() { $x := 1\n ' + call + '\n}',
                'also borrowed', diagnostics=('automatic read-only borrow',))
    fixture('spec34_C_F25_return_local', 'fn bad(p &int) &int { x := 1\n << x }\nfn main() {}', 'cannot return')
    fixture('spec34_C_F25_temporary_rejected', 'fn read(p &int) {}\nfn main() { read(1 + 2) }', 'automatic read-only borrow requires an ordinary place')
    fixture('spec34_C_F25_field_conflict', 'struct Item { value int }\nfn view(p &int) &int { << p }\nfn main() { $x := Item{value: 1}\n s := view(x.value)\n x.value = 2\n println(*s) }', 'because it is borrowed')
    fixture('spec34_C_F25_index_conflict', 'fn view(p &int) &int { << p }\nfn main() { $xs := [1]\n s := view(xs[0])\n xs.push(2)\n println(*s) }', 'element is borrowed')
    fixture('spec34_C_F25_index_boundary', 'fn read(p &int) {}\nfn main() { xs := [1]\n read(xs[0 + 0]) }', 'element borrow index must be a variable or integer literal')
    fixture('spec34_C_F25_unknown_generic', 'fn read#T(p T) {}\nfn main() { x := 1\n read(x)\n println(x) }', output='1\n')

    fixture('spec34_C_anon_return_type', 'fn main() { f := fn() $&int { << 1 } }', 'type mismatch: expected &mut int, found int')

    fixture('spec34_C_anon_parameter', 'fn main() { offset := 1\n f := fn(p $&int) int { << *p + offset }\n $x := 4\n println(f($&x)) }', output='5\n')

    for tag, body in (('plain', 'read(r)'), ('deref', 'read(*r)'), ('explicit', 'read(&*r)')):
        fixture('spec34_C_reborrow_read_' + tag, 'fn read(p &int) int { << *p }\nfn main() { $x := 3\n r := $&x\n println(' + body + ')\n *r = 4\n println(*r) }', output='3\n4\n')
    fixture('spec34_C_D16_last_use_notes', 'fn main() { $x := 1\n let s: &int = x\n x = 2\n println(*s) }', 'because it is borrowed', diagnostics=('automatic read-only borrow inserted', 'read-only borrow is last used here', ':3:16: note:', ':5:2: note:'))

    fixture('spec34_C_typed_writable_binding', 'fn main() { $x := 1\n $y := 2\n let $r: $&int = $&x\n *r = 3\n r = $&y\n *r = 4\n println(*r)\n println(x) }', output='4\n3\n')
    fixture('spec34_C_writable_array_type', 'fn main() { $x := 1\n p := $&x\n a := [1]$&int{&*p}\n println(*a[0])\n *p = 2\n println(*p) }', output='1\n2\n')
    fixture('spec34_C_lifetime_compat', 'fn old(p &mut a int) &mut a int { << p }\nfn new(p $&a int) $&a int { << p }\nfn main() { $x := 3\n p := old($&x)\n q := new(p)\n println(*q) }', output='3\n')
    fixture('spec34_C_F25_generic_instances', 'fn read(p &int) int { << *p }\nfn relay#T(tag T) int { x := 7\n << read(x) }\nfn main() { println(relay(1))\n println(relay(true))\n println(relay(1)) }', output='7\n7\n7\n')

    fixture('spec34_C_F25_no_generic_borrow_inference', 'fn read#T(p &T) {}\nfn main() { x := 1\n read(x) }', 'type mismatch')
    fixture('spec34_C_D18_owning_move', 'fn main() { x := "owned"\n s := x\n println(x)\n println(s) }', 'use of moved value')

    fixture('spec34_C_explicit_writable_receiver', 'struct Item { value int }\nfn (p $&Item) write() { p.value = 9 }\nfn main() { $x := Item{value: 3}\n r := $&x\n (&*r).write()\n println(r.value) }', output='9\n')
    fixture('spec34_C_explicit_builtin_receivers', 'fn main() { $s := "xu"\n p := $&s\n (&*p).push_str("!")\n (&*p).push_byte(33)\n println(*p)\n $a := [1]\n r := $&a\n (&*r).push(2)\n (&*r).push(3)\n println(r[2]) }', output='xu!!\n3\n')
    fixture('spec34_C_explicit_receiver_shared_upgrade', 'struct Item { value int }\nfn (p $&Item) write() { p.value = 9 }\nfn bad(r &Item) { (&*r).write() }\nfn main() {}', 'through a shared reference')
    fixture('spec34_C_explicit_receiver_shared_child', 'struct Item { value int }\nfn (p $&Item) write() { p.value = 9 }\nfn bad(r $&Item) { let s: &Item = r\n (&*r).write()\n println(s.value) }\nfn main() {}', 'frozen reference')
    fixture('spec34_C_D16_receiver_result', 'struct Item { value int }\nfn (p &Item) view() &int { << p.value }\nfn main() { $x := Item{value: 3}\n s := x.view()\n println(*s)\n x.value = 4\n println(x.value) }', output='3\n4\n')
    fixture('spec34_C_D16_receiver_result_conflict', 'struct Item { value int }\nfn (p &Item) view() &int { << p.value }\nfn main() { $x := Item{value: 3}\n s := x.view()\n x.value = 4\n println(*s) }', 'because it is borrowed')

    fixture('spec34_C_explicit_map_receiver', 'fn main() { $m := map[string]int{}\n m["x"] = 1\n r := $&m\n (&*r).delete("x")\n println(r.len()) }', output='0\n')

    fixture('spec34_C_F25_xu_boundary', 'fn worker(p &int) {}\nfn main() { x := 1\n xu worker(x) }', 'type mismatch: expected &int, found int')


def check_phase_c_backends(fixture):
    source = '''struct Item { value int, text string }
fn (p $&Item) write() { p.value = 9 }
fn read(p &int) int { << *p }
fn item(p &Item) int { << p.value }
fn slice(p &[]int) int { << p[1] }
fn text(p &string) string { << *p + "!" }
fn identity(p $&a int) $&a int { << p }
fn write(p $&int) { *p = 9 }
fn main() { let $x: int = 1
 r := identity($&x)
 write(&*r)
 println(read(r))
 println(read(x))
 i := Item{value: 2, text: "xu"}
 println(item(i))
 println(text(i.text))
 a := [3, 4]
 println(slice(a))
 println(read(a[1]))
 items := [Item{value: 5, text: "array"}]
 println(read(items[0].value))
 println(text(items[0].text))
 $i2 := Item{value: 1, text: "receiver"}
 ir := $&i2
 (&*ir).write()
 println(ir.value)
 $a2 := [1]
 ar := $&a2
 (&*ar).push(7)
 println(ar[1])
}'''
    for target, runner in (('host', ()), ('linux-arm64', ('qemu-aarch64',)),
                           ('linux-arm32', ('qemu-arm',)), ('linux-loongarch64', ('qemu-loongarch64',)),
                           ('linux-riscv64', ('qemu-riscv64',))):
        for opt in ('-O0', '-O2'):
            extra = (opt,) if target == 'host' else (opt, '--target', target)
            fixture('spec34_C_backend_' + target + opt, source,
                    output='9\n9\n2\nxu!\n4\n4\n5\narray!\n9\n7\n', extra=extra, runner=runner)
