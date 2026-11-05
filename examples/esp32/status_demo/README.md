# Xu wireless status on ESP32 CYD

This application draws two status cards on an ESP32-2432S028 (original
ESP32, 40 MHz crystal, 4 MiB flash, 320 × 240 LCD). The LCD, touch input,
Wi-Fi station, BLE host, PHY setup and interrupt workers are Xu source.
Chip mask-ROM calls use Xu's explicit ROM ABI bridge. No C application,
vendor radio archive or external linker is used to build the application.
The board must already have a compatible bootloader and the factory
application partition at `0x10000`, length `0x300000`.

The application keeps **Wi-Fi and BLE online together**. One cold PHY setup
starts the Wi-Fi station first, then initializes the BLE controller without
clearing shared memory or recalibrating the active radio. The hardware RF
sequencer restores the actual AP frequency after BLE events, with hardware
arbitration giving BT priority. The header displays `BOTH`.

This is a fixed-profile coexistence application, not a general coexistence
SDK: scanning/retuning happens before BLE starts. Wi-Fi reconnection while
BLE remains connected and dynamic software priority policies are not
implemented. Changing networks requires a joint restart.

## Build and flash

Use the current Xu compiler and standard library from the same checkout.
The builder also needs Python 3 and `xtensa-esp32-elf-nm`, found through
`XTENSA_NM`, `PATH`, or the local Espressif tools directory. Binutils only
reads symbol addresses; it does not compile or link firmware.

Create a **local, untracked** JSON file containing string fields `ssid` and
`password`. Use a WPA2-PSK 2.4 GHz test network; open networks and WPA3 are not
supported by this fixed station profile. Keep this file and generated firmware
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

The status cards depend on `#embedded/display`'s `Surface#T`, which owns typed
backend state, logical dimensions, rectangle filling and RGB565 row writes.
`ui.xu` has no ESP32, GPIO, SPI, controller or radio dependency; its optional
change observer is connected to board UART diagnostics in `diagnostics.xu`.

`st7789.xu` is this board's adapter. `main.xu` selects it with
`st7789_surface_create`; another controller supplies the same two callbacks
and returns a surface with its own backend type. The UI and wireless loop
accept either type without changing their rendering code. The same cards
have also been rendered through `#embedded/display/memory` and a recording
backend on the host. The layout requires at least 320 × 240, and uses the
surface dimensions to expand the cards on larger displays. Touch calibration
and hit regions remain specific to this CYD board.

The surface clips writes, validates RGB565 values and returns backend errors.
The UI stops drawing after an error. A sixteen-pixel scratch row is allocated
once; hardware rendering needs no full framebuffer or allocation per update.
See the [display interface](../../../src/embedded/display/README.md) for the
adapter contract and portable framebuffer example.

- **Wi-Fi:** preparation, connection, actual DHCP IP, gateway test result,
  failure and disconnected state. RSSI is shown as `-- dBm` because the
  backend does not provide a calibrated measurement. Tap the Wi-Fi
  card to request a gateway test. Background tests submit without blocking
  BLE host servicing; only authenticated matching replies update `GW OK`.
- **BLE:** `XU-PURE-HID14`, advertising, connection, encryption/bond and
  keyboard subscription state. Tap its control row to request one F24
  press/release after the host enables notifications. Reports are not sent
  automatically. The display confirms controller submission; an external
  HID observer is needed to verify reception.
- Both cards report actual link state. Touch controls service the selected
  function without rebooting or disconnecting the other radio.

UART is 115200 baud. `k` requests F24, `p` requests a gateway probe and `q`
prints Wi-Fi/BLE/encryption/subscription flags and the real Echo Reply count.

BLE uses a single-peer legacy SMP Just Works bond with two checked flash
slots at `0x310000` and `0x311000`. It restores the key cache after a
reboot, then waits for actual link encryption and fresh CCCD
subscription. A new bond is committed after the real BLE disconnect;
advertising and Wi-Fi DMA are stopped around cache-off flash work, then
reception and advertising resume. Wi-Fi lease and keys remain in RAM during
this brief pause.
Do not erase those sectors or reuse them for another partition. Just Works
does not provide MITM protection or LE Secure Connections. Flash records
contain plaintext keys and must remain private.

## Wiring

| Device | Pins |
| --- | --- |
| LCD | SCK 14, MOSI 13, CS 15, DC 2, backlight 21 |
| XPT2046 touch | CLK 25, MOSI 32, MISO 39, CS 33, IRQ 36 |

Wi-Fi reserves DMA/PHY work at `0x3FFE8000..0x3FFED000`, with normal MAC-dump
mapping required. BLE KE pools remain at `0x3FFD2000..0x3FFD7000`; Wi-Fi copy
scratch is separate from interrupt scratch. Use the radio image layout and
keep IRAM below `0x400A0000` to avoid the upper DRAM alias. The demo checks
DMA, stack and arena guards while running.

The panel uses the previous CYD demo's landscape initialization and touch
calibration. Rendering updates sixteen pixels per event-loop iteration so
radio servicing continues between SPI chunks. The LCD has no image
readback; UART completion proves writes, not visible panel contents.
