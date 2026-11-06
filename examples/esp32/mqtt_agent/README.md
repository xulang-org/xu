# Xu MQTT BLE agent

This hosted Xu CLI uses the same MQTT codec as the board. It subscribes to the
result topic, publishes one validated command without RETAIN, waits for its
matching operation ID, sends PUBACK and disconnects. Exit 0 means an accepted
result, 3 a device rejection, 1 invalid input and 2 a transport error/timeout.
Retry a lost result using exactly the same ID and JSON bytes.

Build from the Xu repository root:

```sh
bin/xu build examples/esp32/mqtt_agent/main.xu -o build/mqtt_agent
build/mqtt_agent 127.0.0.1 xu/esp32/cyd '{"id":"status-1","op":"status"}'
build/mqtt_agent 127.0.0.1 xu/esp32/cyd '{"id":"key-down-1","op":"hid.keyboard","report":[0,0,115,0,0,0,0,0]}'
build/mqtt_agent 127.0.0.1 xu/esp32/cyd '{"id":"key-up-1","op":"hid.keyboard","report":[0,0,0,0,0,0,0,0]}'
```

Arguments are `BROKER_IPV4 TOPIC_ROOT JSON_COMMAND [PORT]`, default port 1883.
The agent must reach the same local test broker as the board. It uses hosted
OS sockets; the board uses the pure Xu cooperative TCP client over Wi-Fi.
Neither client uses a vendor radio archive or C application shim.

The demo's topics are `xu/esp32/cyd/cmd`, `/result` and `/status`. Status carries
actual Wi-Fi, IP, gateway reply count, BLE encryption and three subscription
flags. Status queries also include that snapshot in the matching result.
`queued` confirms acceptance by the board's output queue. Verify actual HID
reception with an external device or OS HID observer.

Use a local Mosquitto broker with an explicit listener for the Mac's LAN IPv4
address and a loopback listener for the agent. The test profile permits
anonymous clients and disables persistence. See
[Mosquitto listener configuration](https://mosquitto.org/man/mosquitto-conf-5.html).
Firmware selects this address using `build_demo.py --mqtt-broker LAN_IPV4`;
it does not use the broker's loopback address. A broker restart reconnects and
resubscribes while the BLE link remains active. Wi-Fi network changes still
require a joint radio restart.
