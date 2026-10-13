# Xu documentation

## doc/sample

Source: `tests/doc/basic.xu`

### Imports

- `#strings`
- `#path/filepath as fp`

Answer to life, the universe, and everything.

### pub const Answer
```xu
pub const Answer = 42
```

### pub const Greeting
```xu
pub const Greeting = "hello\nworld"
```

A documented record.

### pub struct Box#T

```xu
pub struct Box#T {
    pub value T
    label string
}
```

A documented state machine.

### pub enum State

```xu
pub enum State {
    Ready
    Done(string)
}
```

A small structural interface.

### pub struct@ Reader

```xu
pub struct@ Reader {
    fn read([]u8) int
}
```

Identity preserves its value.

### pub fn identity#T(x T) T

### pub fn borrow(a &a string) &a string

A method with a mutable receiver.

### pub fn (b &mut Box#string) set(v string)
