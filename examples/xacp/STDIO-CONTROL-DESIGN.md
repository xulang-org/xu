# Historical note: XACP stdio control

The authoritative description of the implemented protocol is
[PROTOCOL.md](PROTOCOL.md). Use it for framing, authentication, permissions,
timeouts, operations, transport behavior, and platform limitations.

This file originally described the initial stdio control design. Its lasting
architectural choice is an explicit exclusive control entry that skips business
`main`, leaving ordinary startup free of control-input probing. The implemented
system also provides loopback TCP and explicit library attachment, where business
`main` runs and the Screen owner services control jobs through channels.

The original proposal is superseded. It is not a second specification and does
not define current wire syntax, permission defaults, or implementation status.
