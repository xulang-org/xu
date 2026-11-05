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
LCD panel driver (`status_lcd.c`: init, rectangle fill, one-row pixel span)
and FreeRTOS. `main/xu_host.c` exposes them to Xu as `c_call6("xu_host_*",
...)` services (TCP bytes, HID state/reports, Wi-Fi state, logging, LCD
fill/span), allocates the 64 KiB Xu heap before Wi-Fi/BT start, and runs the
Xu loop in its own task (started before Wi-Fi so the screen comes up first).

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
- Xu talks to C one word at a time through `c_call6` (six int arguments, int
  result); bytes cross the boundary individually.
- Status screen is read-only; touch input is not wired yet. It can only draw
  the CJK glyphs in `status_demo/font.xu`; after changing that font, run
  `python3 scripts/gen_status_font.py` to regenerate the compact `xu/font.xu`.
- The first full dashboard frame takes ~3 s (each 16-pixel span crosses
  `c_call6` five pixels at a time); later updates redraw only changed fields.
- Classic ESP32 only in this pin; S3/C3 are out of scope here.
