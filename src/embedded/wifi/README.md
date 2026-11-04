# Wi-Fi protocol building blocks

`#embedded/wifi` supplies bounded beacon/Probe Response selection,
open-system authentication and association, and WPA2-PSK/CCMP pairwise
handshake primitives. Association is separate from key installation and IP.
The caller validates M3 key data and installs fresh keys before confirming M4;
retries reuse cached responses without asking for a key reinstall.

The separate packages keep optional code out of small firmware images:

- `#embedded/wifi/key_data`: RFC 3394 AES-128 unwrap and strict RSN/GTK KDE
  validation for the supported WPA2 profile.
- `#embedded/wifi/ccmp`: software CCMP-128 for three-address Data/QoS Data,
  with MIC verification and explicit six-byte PN/replay-floor handling.
- `#embedded/wifi/ipv4`: DHCP acquisition, matching ARP replies, and validated
  ARP/ICMP request responses and Echo probes over authenticated LLC payloads.
- `#embedded/wifi/session`: one owning device context, replay state and
  width-independent lease countdown, with no hardware access.

The station owner must check peer addresses and complete DMA frame boundaries,
retain per-key/per-transmitter/per-TID replay state, consume each transmit PN
before submission, handle retries and disconnects, and stop traffic when a
lease expires. No package releases unauthenticated CCMP plaintext as success.
AES and the handshake code do not promise constant-time execution or secure
erasure.

For the measured ESP32 raw DMA configuration,
`#embedded/chips/esp32/wifi_raw_ccmp` selects software CCMP reception while
retaining the caller's hardware ACK address. Its preconditions require a
stopped receiver and no native keys. `wifi_rx_layout` separately provides a
bounded, allocation-free decoder for the supported FCS-stripped DMA profile
and native CSI layout cases.

The separate opt-in [`wifi_radio` backend](../chips/esp32/wifi_radio/README.md)
initializes the measured ESP32 PHY/MAC profile and activates `WifiDevice`
connection, polling, disconnect, reconnect and gateway probes. Its scope and
radio/memory ownership requirements are explicit. Default hooks, general scan
and SoftAP remain unavailable. DHCP renewal, DNS/TCP, address-conflict handling,
group-key rekey and BLE/Wi-Fi coexistence remain outside this profile.
