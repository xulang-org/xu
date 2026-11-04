# CCMP-128

Pure Xu IEEE 802.11 CCMP-128 using `#crypto/aes`. Inputs and outputs are byte
strings. `protect` returns a complete MPDU without FCS; `unprotect` returns an
authenticated payload fragment. It does not establish a wireless link or
reassemble fragments.

Supported headers are 24-byte three-address Data and 26-byte three-address
QoS Data, protocol version zero. Four-address, HT Control/Order, A-MSDU,
management, and other Data subtypes are rejected. Complete protected frames
are limited to 1600 bytes, including the MAC header, CCMP header, and MIC.

```xu
#embedded/wifi/ccmp

// Once for each fresh installed transmit key:
$tx_pn := make_string(6)
// Before encrypting each new frame:
next := ccmp.next_pn(&tx_pn)
// Empty next means exhausted: stop using this key.
tx_pn = next
frame := ccmp.protect(&key, &header, &payload, &tx_pn, key_index)

// Select the actual installed receive key from the CCMP Key ID first.
packet := ccmp.unprotect(&key, &received_frame, &rx_pn)
if packet.valid {
    rx_pn = packet.pn
    // Now dispatch packet.payload, with addresses/TID from the MAC header.
}
```

Every PN is **six little-endian octets**, including replay floors. This avoids
48-bit integer truncation on ESP32. Zero is an initial floor and is rejected as
a transmitted PN. `next_pn` returns empty for invalid input or exhaustion and
never wraps. Consume a PN before encryption/submission, retain it on failure,
and never reset it while reusing a key. Reinstalling the same key must preserve
its counters. Retransmit a previously protected frame unchanged; do not encrypt
different contents with its PN. `protect` is stateless and cannot detect caller
reuse.

Use a separate receive floor per installed key, transmitter, and traffic ID,
with a non-QoS replay domain. Reject PN values at or below that floor. Advance
the floor after `valid=true`, before payload dispatch. Invalid results contain
no payload or PN. The caller must validate the expected addresses, fragment
handling, and selected key. Key ID is returned in `packet.key_index`; IEEE CCMP
does not include that field in its authenticated data.

AES errors are handled internally. The MIC comparison visits all eight bytes,
but the underlying AES implementation is variable-time. Authentication does
not imply confidentiality against local timing observation.

AAD masking, the 13-byte nonce, and CCM with L=2/M=8 were checked against local
ESP-IDF `components/wpa_supplicant/src/crypto/ccmp.c` and `aes-ccm.c`. Independent
host validation uses Python `cryptography` AESCCM with 12 complete MPDU vectors,
both header layouts, block-boundary and maximum payload lengths, tampering,
IEEE-masked fields, malformed headers, replay rejection, and 48-bit PN carry
and exhaustion. Test artifacts are under ignored `build/esp32-wifi/ccmp-*`.
Hardware execution is a separate integration check.
