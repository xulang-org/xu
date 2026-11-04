# ESP32 with pure Xu

The `xtensa-esp32-none` target emits ELF32 Xtensa code directly. The image
packer produces an ESP32 application image without a GCC linker, C HAL, or
vendor controller/PHY archive. Chip mask-ROM helpers use the explicit
windowed ABI bridge. An existing compatible ESP32 bootloader and partition
table are required; they are not included here.

Build the UART console from this directory:

```sh
make XU=/absolute/path/to/xu
make flash XU=/absolute/path/to/xu PORT=/dev/cu.usbserial-2110
```

`make` builds and verifies only; `make flash` writes the application at
`0x10000`. The console prints the CPU frequency and echoes UART input. It
does not initialize a radio or write bond storage.

## Memory and ABI

The default `esp32` profile executes from IROM. `--board esp32-iram` emits a
bounded native module in `0x40080000..0x400A0000`. Keep every helper reachable
while flash cache is disabled in IRAM or mask ROM. `rom_callback` accepts a
named free function with at most six `int` arguments and an `int` result;
`rom_call6` uses a constant aligned executable entry and six word arguments.

Radio images reserve Xu data/heap in `0x3FFC0000..0x3FFD2000` and the stack
below `0x3FFE0000`, outside the mask-ROM controller state and exchange memory.
The packer's `--radio` checks these bounds. `pack-multi` can combine a primary
ELF and a code-only Xu IRAM module; all load segments must have distinct,
valid memory ranges.

## Wireless implementation boundaries

`#embedded/bluetooth` provides HCI/H4 framing, ATT/HOGP, legacy SMP Just Works,
ACL credit handling and a portable single-peer bond record codec. The chip
package provides PHY calibration, ROM transport/IRQ support, AES and entropy
bindings. These are building blocks: an application must wire the actual
controller events and enforce encryption/subscription gates before reporting
HID input as sent. Just Works does not provide MITM authentication or LE
Secure Connections.

`#embedded/chips/esp32/flash` implements fixed-profile two-slot bond storage
for a 4MiB device. It validates partition ownership and rejects encrypted
flash; writes require a disconnected/stopped radio, a stopped APP CPU and
an entirely IRAM/ROM execution closure. Records contain plaintext keys and
must not be logged. Persistence restores a key cache, not an encrypted link
or subscribed CCCDs.

`#embedded/wifi` parses bounded, FCS-stripped beacon MPDUs from opaque bytes
or checked `[]int` bytes. The caller must first validate completed DMA,
hardware RX status and packet length. The parser reports observed SSID,
BSSID, DS channel, interval and privacy bit; it does not infer a WPA mode.
The standard ESP32 `WifiDevice` scan/connect/AP APIs currently return failure
instead of fabricating networks or IP leases. Wi-Fi association, DHCP,
simultaneous BLE/Wi-Fi, and a complete public radio application are not
provided by this console example.
