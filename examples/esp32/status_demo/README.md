# Xu wireless status on ESP32 CYD

This application draws two status cards on an ESP32-2432S028 (original
ESP32, 40 MHz crystal, 4 MiB flash, 320 × 240 LCD). The LCD, touch input,
Wi-Fi station, BLE host, PHY setup and interrupt workers are Xu source.
Chip mask-ROM calls use Xu's explicit ROM ABI bridge. No C application,
vendor radio archive or external linker is used to build the application.
The board must already have a compatible bootloader and the factory
application partition at `0x10000`, length `0x300000`.

The two radios run in **exclusive modes**. Tapping the other card disconnects
the active link and restarts into that mode. This application does not
implement simultaneous BLE/Wi-Fi coexistence. The current mode survives a
software reset in the final 16 bytes of RTC slow RAM; a cold boot defaults
to Wi-Fi. No ULP program may use those bytes.

## Build and flash

Use the current Xu compiler and standard library from the same checkout.
The builder also needs Python 3 and `xtensa-esp32-elf-nm`, found through
`XTENSA_NM`, `PATH`, or the local Espressif tools directory. Binutils only
reads symbol addresses; it does not compile or link firmware.

Create a **local, untracked** JSON file containing string fields `ssid` and
`password`. Use the password of the WPA2-PSK 2.4 GHz test network; for an
open network use an empty password. Keep this file and generated firmware
private: credentials are embedded in the resulting image.

From the Xu repository root:

```sh
python3 examples/esp32/status_demo/build_demo.py \
  --xu-root . --network-config /absolute/private/network.json \
  --out build/esp32-status
python3 -m esptool --chip esp32 --port /dev/cu.usbserial-2110 \
  --baud 460800 write_flash 0x10000 build/esp32-status/wireless_status.bin
```

The builder compiles the scalar interrupt/flash closure into IRAM, resolves
its callback symbols, builds the application into IROM, and verifies the
packed image. It rejects images that cross the factory partition boundary.
Generated sources and binaries stay in the private output directory.

## Display and controls

- **Wi-Fi:** preparation, connection, actual DHCP IP, gateway test result,
  failure and disconnected state. RSSI is shown as `-- dBm` because the
  backend does not provide a calibrated measurement. Tap the active Wi-Fi
  card to test the gateway, or reconnect after failure/disconnection.
- **BLE:** `XU-PURE-HID14`, advertising, connection, encryption/bond and
  keyboard subscription state. Tap its control row to request one F24
  press/release after the host enables notifications. Reports are not sent
  automatically. The display confirms controller submission; an external
  HID observer is needed to verify reception.
- Tapping the inactive card changes radio mode. The other card shows
  standby rather than claiming that its radio is connected.

UART is 115200 baud. `b` selects BLE from Wi-Fi, `w` selects Wi-Fi from
BLE, `k` requests F24, `p`/`r` tests the gateway or reconnects Wi-Fi, `x`
disconnects Wi-Fi, and `q` prints its actual IP. From an initialization
failure screen, `b`/`w` selects the next mode.

BLE uses a single-peer legacy SMP Just Works bond with two checked flash
slots at `0x310000` and `0x311000`. It restores the key cache after a mode
change, then waits for actual link encryption and fresh CCCD subscription.
Do not erase those sectors or reuse them for another partition. Just Works
does not provide MITM protection or LE Secure Connections. Flash records
contain plaintext keys and must remain private.

## Wiring

| Device | Pins |
| --- | --- |
| LCD | SCK 14, MOSI 13, CS 15, DC 2, backlight 21 |
| XPT2046 touch | CLK 25, MOSI 32, MISO 39, CS 33, IRQ 36 |

The panel uses the previous CYD demo's landscape initialization and touch
calibration. Rendering updates sixteen pixels per event-loop iteration so
radio servicing continues between SPI chunks. The LCD has no image
readback; UART completion proves writes, not visible panel contents.
