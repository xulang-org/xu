# IPv4 bootstrap

`#embedded/wifi/ipv4` supplies pure Xu byte codecs for initial DHCP acquisition
and a gateway ARP/ICMP probe. It has no OS, C, radio, or crypto dependency. All
IPv4 addresses, DHCP XIDs, and lease times are four network-order bytes stored
in strings, including bytes with the high bit set and embedded NULs.

Create a client using the real six-byte station MAC and a fresh unpredictable
four-byte XID. `client.discover()` returns a complete LLC/SNAP + IPv4 + UDP +
DHCPDISCOVER payload and enters `DHCP_SELECTING`. Pass authenticated decrypted
LLC payloads to `client.receive_llc(&payload)`. A matching valid offer records
`offered` and `server` and enters `DHCP_REQUESTING`; `address` remains empty.
`client.request()` returns the broadcast DHCPREQUEST selecting those values.
Only a valid matching ACK after that request was generated populates `address`,
`mask`, `router`, and `lease_seconds` and enters `DHCP_LEASED`. A matching NAK
enters `DHCP_FAILED`. A true receive result means an accepted state transition,
so callers must inspect `state` before using the configuration.

`receive_ethernet(&frame)` accepts an Ethernet II frame without FCS or VLAN
tags. This is useful for packet fixtures or an independently authenticated
bridge. The normal 802.11 data path uses `receive_llc` after CCMP verification,
replay checking, and any supported deaggregation. The caller wraps all outgoing
LLC payloads in its own protected 802.11 frames.

After acquisition, `arp_request(&mac,&address,&router)` returns an LLC ARP
request. `arp_reply_mac(&payload,&mac,&address,&router)` returns a six-byte MAC
only for a valid matching ARP reply. Send `echo_request(&address,&router,id,
sequence,&body)` to that MAC. `echo_reply_valid(&payload,&address,&router,id,
sequence,&body)` checks the reverse IP addresses, ICMP type/code, identifier,
sequence, full body, and both checksums. These are neighbor and gateway checks;
they do not establish Internet connectivity.

The bounded profile accepts IPv4 datagrams up to 1500 bytes with a 20-byte
header, a nonzero TTL, no fragmentation, and a correct header checksum.
Ethernet minimum-size padding (46 bytes after the EtherType) is outside the
IP datagram and is ignored even when nonzero; other trailing bytes must be
zero. UDP lengths must match the IP datagram;
nonzero UDP checksums must verify. IPv4 UDP checksum zero is valid. DHCP checks
the transaction, Ethernet hardware type/length, station MAC, cookie, options,
selected server, and offered address. ACKs need a nonzero lease, contiguous
`/1` through `/30` mask, usable host address, and distinct usable on-subnet
router. DHCP option overload and duplicate critical options are unsupported
and rejected. Client-ID echo is optional; when present it must match.

The driver owns retry clocks and successful transmission, lease expiration and
renewal, duplicate-address detection and DHCPDECLINE, ARP response/cache policy,
and all higher-layer traffic. The client does not claim that an ACK proves an
address is conflict-free, and does not implement TCP or DNS.

Wire layout and option checks were cross-checked against the installed
ESP-IDF lwIP sources (`src/core/ipv4/dhcp.c`, `src/core/ipv4/ip4.c`,
`src/core/udp.c`, `src/include/lwip/prot/dhcp.h`),
[RFC 768](https://www.rfc-editor.org/rfc/rfc768.html),
[RFC 2131](https://www.rfc-editor.org/rfc/rfc2131.html), and
[RFC 2132](https://www.rfc-editor.org/rfc/rfc2132.html). The ignored development harness is
`build/esp32-wifi/ipv4-oracle.py`; it uses Python's standard library as an
independent checksum and packet construction oracle and generates Xu rejection
fixtures. It runs with the task's `0.11.3-dev.10` compiler and an explicit
`XU_STDLIB_ROOT` pointing to this checkout's `src` directory.
