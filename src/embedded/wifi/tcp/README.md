# Cooperative TCP client

`#embedded/wifi/tcp` implements one bounded IPv4 active-open connection in Xu,
without OS sockets, a radio dependency or a C runtime. It exchanges complete
LLC/SNAP + IPv4 + TCP packets with an authenticated link owner.

`create` or `reset` takes local/remote four-byte IP strings, ports, a fresh
unpredictable four-byte initial sequence and a millisecond clock. Sequence
arithmetic remains byte based on 32-bit and 64-bit targets. Submit `poll(now)`
output, pass validated-link packets to `receive`, drain `read()` and check
`connected()`, `failed()` and `writable()` before `write(&bytes)`.

The codec validates IPv4 and TCP checksums, tuple, lengths, fragmentation,
options and stream edges. It advertises MSS 1200, honors the peer MSS/window,
uses stop-and-wait transmission, retransmits boundedly, trims duplicate
prefixes, acknowledges out-of-order data and handles peer close/reset.
Both application buffers are bounded to 2048 bytes. The receive path drops
out-of-order data for retransmission rather than keeping a reassembly tree.
Zero-window connections wait for a window update; the application supplies
its own idle deadline. IPv4 options, timestamps, window scaling, SACK, a
listening server, DNS and TLS are outside this profile.

The ESP32 adapter's `open_tcp`, `resolve_tcp` and `send_tcp` operate on the
owning Wi-Fi session. Its four-packet mailbox is filled only after CCMP
validation; drain `session.take_tcp` outside the radio receive call stack.
The CYD demo resolves the local broker with ARP. A routed peer requires the
gateway MAC to have been resolved first. An unconfirmed Wi-Fi submission is
not treated as a TCP acknowledgment; TCP retains its retransmission state.

See [RFC 9293](https://www.rfc-editor.org/rfc/rfc9293.html) for the full TCP
contract. This small active client is not a general socket stack.
