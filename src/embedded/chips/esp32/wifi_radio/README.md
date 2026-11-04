# ESP32 polling station backend

`#embedded/chips/esp32/wifi_radio` supplies an explicitly installed pure Xu
backend for `esp32.WifiDevice`. It initializes the measured PHY/MAC profile,
selects a directed Probe Response or beacon, authenticates and associates,
completes WPA2-PSK/CCMP, acquires an IPv4 DHCP lease, and services received
frames through `poll`. Mask-ROM primitives are used; no ESP-IDF Wi-Fi binary,
C shim, native Wi-Fi task, or operating system is linked into the application.

```xu
@main

#embedded/chips/esp32
#embedded/chips/esp32/wifi_radio

fn main() int {
    $device := esp32.wifi_create()
    if !device.install_backend(wifi_radio.backend()) || !device.init() { << 1 }
    // Supply deployment credentials privately when building your firmware.
    if !device.connect("YOUR-SSID", "YOUR-PASSPHRASE") { << 2 }
    if !device.ping_gateway(5000) { << 3 }
    while device.poll(20) {}
    device.disconnect()
    << 0
}
```

Build with `xu build main.xu --target xtensa-esp32-none -o firmware.elf`, then
pack using `python3 scripts/esp32_image.py pack firmware.elf firmware.bin
--radio`. Bootloader and partition provisioning are separate. The default
`wifi_create()` hooks remain unavailable until a backend is installed.

The supported hardware profile is ESP32-D0WD-V3 rev 3.1, 40 MHz crystal,
Wi-Fi-only cold boot, channels 1 through 11, legacy open-system management and
WPA2-PSK with CCMP-128. Passphrases contain 8 through 63 printable ASCII bytes;
SSIDs contain 1 through 32 bytes. `connect_timeout` accepts 1 through 300000 ms
and bounds scan/retry scheduling; synchronous PBKDF2 or an in-progress frame
can finish after that deadline. `connect` uses 60000 ms. Open/WEP/WPA3, PMF,
A-MSDU, fragmented IP, roaming, SoftAP, and simultaneous BLE operation are
unsupported. The hardware/profile restrictions are substantive.

One device owns the radio, DMA arena and TIMG0/T0 for its lifetime. The timer
uses APB at 80 MHz; initialization refuses an already enabled T0. `disconnect`
stops RX/TX, releases session keys and cached handshake material, and revokes
the visible IP; it retains PHY initialization, timer ownership, and the facade's
credentials for `reconnect`. A new connection performs a fresh handshake,
SNonce, key installation, replay floors and DHCP XID. It does not resume old
packet-number counters under an old key. There is no background thread or
automatic reconnect: the application must service `poll(0..100)` regularly and
call `reconnect` after a reported disconnection.

The device owns one inline session context and passes it by typed borrow.
Treat `session` and `backend` as device implementation state. Use the facade
getters and borrowed helper arguments instead of copying large protocol
values through application call chains. Do not copy or mutate session state
while the device is active.
The radio layout reserves Xu data and its bounded heap at
`0x3FFC0000..0x3FFD2000`, RX DMA at `0x3FFD2000..0x3FFD5500`, PHY/TX/ROM work
below `0x3FFD8000`, and a downward stack from `0x3FFE0000`. Management, CCMP,
and IPv4 processing use successive call frames. Application call chains must
also respect this 32 KiB stack budget; the product runtime does not supply a
general stack-overflow guard.

Hardware own-address ACK remains enabled. Native key slots stay empty;
complete RX MPDUs are checked for hardware status, layout, peer addresses,
CCMP MIC and per-key/per-TID PN before plaintext reaches DHCP/ARP/ICMP.
Each outgoing PN is consumed before queue submission. RX descriptors are
consumed once and recycled only after stopping DMA. This initial polling
profile retires a TX submission before buffer reuse using a bounded delay;
it does not expose delivery confirmation, contention-controlled retries or a
general data-send API.

The station answers ordinary authenticated ARP requests and valid ICMP Echo
Requests to its leased address. `ping_gateway` verifies full matching replies.
An expired local lease, AP silence, received deauthentication/disassociation,
or fatal DMA/submission failure revokes the connection. Lease seconds use
network-order bytes and a wrapping monotonic clock. DHCP renewal/rebinding,
duplicate-address detection/DECLINE, group-key rekey, DNS and TCP are still
unimplemented. Do not interpret a lease or gateway reply as proof of Internet
access or a complete network stack. RSSI is unmeasured (`has_rssi()` is false).
AES and software supplicant code do not promise constant-time execution or
secure memory erasure.

Board acceptance exercises real WPA2, DHCP, repeated gateway replies,
persistent reception, fresh-key reconnection and an external computer's Echo
Requests. Parser/crypto rejection tests and synthetic facade tests are
separate from that radio evidence.
