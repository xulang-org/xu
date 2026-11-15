# Xu IDF CYD — official BT/Wi-Fi static libraries

Delivery firmware for phone control on ESP32-2432S028 (classic ESP32).
**Radio comes from ESP-IDF’s official static libraries** (`libbtdm*`, Wi-Fi,
coexist/PHY as pulled by the IDF build). The pure-Xu coexistence demo under
`examples/esp32/status_demo/` is experimental and is not this delivery path.

This port keeps the MQTT command envelope and **absolute** mouse reports
(`0..32767`) used by the Xu host agent, so taps do not accumulate relative
offset. The CYD LCD shows the `status_demo` dashboard: Xu draws it with
`status_demo/ui.xu` over `#embedded/display`, and C only pushes the pixels
through ESP-IDF `esp_lcd`.

## Xu application, C host

The MQTT client and command handling are Xu: `xu/app.xu` uses
`#embedded/mqtt` and `#embedded/bluetooth/control`. The build compiles it with
the repository's `bin/xu` (`make bin/xu` first) into an Xtensa relocatable
object (`--target xtensa-esp32-none --emit-obj -o xu_app.o`) that links into
the `main` component. CMake stages `xu/*.xu` (app, screen backend, compact
font) together with `status_demo/ui.xu` and compiles them as one program.

C keeps what the official libraries own: Wi-Fi, BLE HID (`hid_abs.c`), the
LCD panel driver (`status_lcd.c`: init, rectangle fill, pixel spans coalesced
into one SPI transfer per rectangle) and FreeRTOS. `main/xu_host.c` exposes
them to Xu as `c_call6("xu_host_*", ...)` services (TCP send/receive, HID
state/reports, Wi-Fi state, logging, LCD fill/write/flush), allocates the
64 KiB Xu heap before Wi-Fi/BT start, and runs the Xu loop in its own task
(started before Wi-Fi so the screen comes up first).

`c_call6` arguments are int words or borrowed buffers: `&s` / `$&s` for a
string passes its byte pointer, `&a` for a `[]int` passes a pointer to 8-byte
little-endian elements. Pass the length as a separate word (read it before
the borrow); the pointer is valid only for the duration of the call.

## Pin and install

```text
examples/esp32/idf_cyd/IDF_VERSION  →  v5.3.2
```

Install that ESP-IDF tag for ESP32, then:

```sh
. $IDF_PATH/export.sh
cd examples/esp32/idf_cyd
./scripts/build.sh --ssid 'YOUR_SSID' --password 'YOUR_PSK' \
  --mqtt-uri 'mqtt://BROKER_LAN_IPV4:1883'
idf.py -p /dev/cu.usbserial-2110 flash monitor
```

Credentials are sdkconfig values from the build script; do not commit them.
Use a WPA2-PSK 2.4 GHz LAN and an anonymous Mosquitto listener on the broker
LAN address (same profile as the Xu MQTT agent).

## MQTT / HID contract

Topics: `xu/esp32/cyd/cmd`, `/result`, `/status` (override with `--topic-root`).

| op | report |
| --- | --- |
| `status` | empty |
| `advertising.start` / `stop` | empty |
| `disconnect` / `release.all` | empty |
| `hid.keyboard` | 8 bytes |
| `hid.mouse` | **5 bytes** buttons + LE X + LE Y, each axis `0..32767` |
| `hid.consumer` | 1 byte bitmap `0..31` |
| `wifi.reset` | empty |

`wifi.reset` erases the stored Wi-Fi/MQTT settings from NVS and reboots the
node into BLE provisioning mode.

## Two-stage start: BLE provisioning, then BLE HID

The node only advertises as a HID keyboard/mouse **after** it has an IP
address. The stages are:

1. **Stage 1 (no Wi-Fi yet)** — the node advertises `XuPlay-Setup-XXXX`
   (last two bytes of the Bluetooth MAC) and serves a provisioning GATT
   service:
   - `0xFF00` service
   - `0xFF01` config, write: `{"ssid","pass","mqtt_uri","root","name"}`
   - `0xFF02` status, read/notify: `{"state":"provisioning|connecting|connected|failed", ...}`

   Hold the BOOT button (GPIO0) at power-on to force this stage even when a
   Wi-Fi configuration is stored.

2. **Stage 2 (Wi-Fi connected)** — on `IP_EVENT_STA_GOT_IP` the node stores
   the configuration in NVS namespace `xu_cfg`, stops the provisioning
   service, connects to the MQTT broker under `xu/esp32/<root>/cmd` and
   advertises as the HID device, serving up to four phones.

So a fresh node needs no firmware change: the Mac writes the Wi-Fi and MQTT
settings once, and every later boot skips Stage 1. `wifi.reset` sends the
node back to Stage 1.

Absolute center tap via the Xu agent:

```sh
bin/xu build examples/esp32/mqtt_agent/main.xu -o build/mqtt_agent
build/mqtt_agent BROKER_IPV4 xu/esp32/cyd '{"id":"tap-move-1","op":"hid.mouse","report":[0,255,63,255,63]}'
build/mqtt_agent BROKER_IPV4 xu/esp32/cyd '{"id":"tap-down-1","op":"hid.mouse","report":[1,255,63,255,63]}'
build/mqtt_agent BROKER_IPV4 xu/esp32/cyd '{"id":"tap-up-1","op":"hid.mouse","report":[0,255,63,255,63]}'
```

`release.all` releases at the **last** absolute point (never drags to `(0,0)`).

After flashing, forget/re-pair the phone if it previously bonded to the pure-Xu
Report Map.

## Known issues

**The LCD dashboard is disabled.** `xu/screen.xu` draws the status panel from
the same task that keeps the MQTT session alive. Each non-contiguous span
flushes the panel on its own and waits for the transfer-done event, so one
frame queues dozens of spans and the task spends seconds inside a single
tick. The MQTT keepalive then misses, the broker drops the node and the node
never reconnects — while the phones stay connected over BLE, which makes the
symptom look like an MQTT problem.

The panel still initialises (`status_lcd_start`), but `screen_tick` is not
called from the main loop until the draw path is fixed. `flush_at` also
bounds its wait now: a missed transfer-done interrupt skips one frame
instead of hanging the task forever.

**Only one phone name arrives per boot.** The GATT client opens one link at
a time, so with several phones connected the later peers keep an empty name
until the next connect. The node still reports every peer by BDA; bind the
missing one by hand with `pl esp bind <phone> <mqtt_topic> <slot>`.

**The GATT client channel must stay open.** The client that reads the
phone name over `0x2A00` shares the ACL link with the HID service on
classic Bluetooth. Closing it (`esp_ble_gattc_close`) tears down the
phone's own link — the phone disconnects with reason `0x16` and reconnects,
which repeats for every peer.

## Size gate

`scripts/build.sh` fails when the application `.bin` exceeds 2097152 bytes
(2 MiB) unless `--size-limit` overrides. `partitions.csv` gives the factory app
3 MiB of the 4 MiB flash: the C-only build fit the stock 1.5 MiB table, the Xu
MQTT app plus dashboard (~340 KiB of Xu code) does not.
rewrote the controller in Xu source was ~3.13 MiB and is not the size target.

## Host checks without IDF

```sh
python3 scripts/test_idf_cyd_control.py
```

## Limits

- LAN anonymous MQTT, no TLS/DNS. The broker address is fixed at build time;
  rebuild if the broker host's LAN address changes.
- Status screen is read-only; touch input is not wired yet. It can only draw
  the CJK glyphs in `status_demo/font.xu`; after changing that font, run
  `python3 scripts/gen_status_font.py` to regenerate the compact `xu/font.xu`.
- The first full dashboard frame takes ~0.8 s, mostly Xu glyph rasterization;
  later updates redraw only changed fields.
- Classic ESP32 only in this pin; S3/C3 are out of scope here.
