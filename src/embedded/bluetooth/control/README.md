# BLE command envelopes

`control.parse(&json)` validates a bounded ASCII JSON command for a peripheral
application. It performs no radio or HID operation. `Command.op` is an enum;
`valid` must be checked before using the ID or report. Failed parses return
an empty invalid command.

```json
{"id":"keyboard-1","op":"hid.keyboard","report":[0,0,115,0,0,0,0,0]}
```

An ID contains 1..64 letters, digits, dots, underscores or hyphens. The only
fields are `id`, `op` and optional `report`. Duplicate/unknown fields, escaped
strings, non-ASCII names, malformed JSON and input over 512 bytes are rejected.

| Operation | Report |
| --- | --- |
| `status` | absent or empty |
| `advertising.start`, `advertising.stop` | absent or empty |
| `disconnect`, `release.all` | absent or empty |
| `hid.keyboard` | eight bytes: modifiers, zero reserved byte, six usages 0..115 |
| `hid.mouse` | four bytes: buttons 0..7, X, Y, wheel; signed axes encoded as bytes, 128 rejected |
| `hid.consumer` | one bitmap byte 0..31, matching the HOGP descriptor |

The application still checks actual encryption, CCCD subscription, controller
credits and queue capacity. Parsing a valid report establishes none of those
permissions. The CYD MQTT application supplies those gates, caches the latest
sixteen operation IDs in RAM and releases tracked held reports after a
one-second software deadline or transport loss. A new unique ID refreshes
that deadline; replaying an existing ID does not repeat the action.
