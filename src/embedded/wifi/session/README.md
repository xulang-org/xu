# Owning station context

`#embedded/wifi/session` carries the station's selected AP, supplicant,
software CCMP key/PN state, DHCP owner, lease budget and bounded diagnostics.
It performs no MMIO. A hardware backend exclusively borrows one `State` from
the device rather than sharing mutable package globals. Construct an invalid
owner with `create()`; `fresh_keys()` creates separate replay floors for the
16 QoS TIDs and the ordinary Data domain. It does not install a key.

`elapsed` operates on milliseconds modulo 2^31; polling gaps must be shorter
than half that range. `lease_tick` subtracts seconds from a big-endian unsigned
32-bit countdown without depending on the target's integer width. Empty
output means expiry or invalid input. `leased` checks both the backend's link
state and the DHCP owner's lease state; the backend must revoke both on loss.

The `error` field records the connect phase reached before a failure: scan
(1), key preparation (2), association/handshake (3), raw reception policy (4),
or DHCP (5). A successful connect clears it to zero. It is a phase diagnostic,
not an IEEE status/reason code. Packet counters never log keys or payloads.
