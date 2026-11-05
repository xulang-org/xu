# Xu IDF CYD — official BT/Wi-Fi static libraries

Delivery firmware for phone control on ESP32-2432S028 (classic ESP32).
**Radio comes from ESP-IDF’s official static libraries** (`libbtdm*`, Wi-Fi,
coexist/PHY as pulled by the IDF build). The pure-Xu coexistence demo under
`examples/esp32/status_demo/` is experimental and is not this delivery path.

This port keeps the MQTT command envelope and **absolute** mouse reports
(`0..32767`) used by the Xu host agent, so taps do not accumulate relative
offset. The first delivery is UART/headless (no CYD LCD glyph tables) to keep
the application image under the **1.5 MiB** soft size gate.

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

`scripts/build.sh` fails when the application `.bin` exceeds 1572864 bytes
(1.5 MiB) unless `--size-limit` overrides. The pure-Xu coexistence image that
rewrote the controller in Xu source was ~3.13 MiB and is not the size target.

## Host checks without IDF

```sh
python3 scripts/test_idf_cyd_control.py
```

## Limits

- LAN anonymous MQTT, no TLS/DNS.
- Headless first delivery (LCD/touch follow-up can use IDF display drivers).
- Classic ESP32 only in this pin; S3/C3 are out of scope here.
