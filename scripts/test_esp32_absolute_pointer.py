#!/usr/bin/env python3
"""Contract checks for absolute BLE HID pointer targeting (no phone offset).

Relative mouse deltas drift on phones. Absolute X/Y in 0..32767 plus
release-at-last-point keep taps on the commanded screen position.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
HOGP = (ROOT / "src/embedded/bluetooth/hogp.xu").read_text()
ATT = (ROOT / "src/embedded/bluetooth/att.xu").read_text()
CONTROL = (ROOT / "src/embedded/bluetooth/control/command.xu").read_text()
CONTROL_README = (ROOT / "src/embedded/bluetooth/control/README.md").read_text()
MQTT = (ROOT / "examples/esp32/status_demo/mqtt_app.xu").read_text()
TRANSPORT = (ROOT / "examples/esp32/status_demo/ble_transport.xu").read_text()

ABS_MAX = 32767


def scale_axis(pixel: int, span: int) -> int:
    if span <= 1:
        return 0
    if pixel <= 0:
        return 0
    if pixel >= span - 1:
        return ABS_MAX
    return (pixel * ABS_MAX) // (span - 1)


def mouse_section(src: str) -> str:
    start = src.index("// Mouse Report")
    end = src.index("// Keyboard Report")
    return src[start:end]


def fail(msg: str) -> None:
    raise AssertionError(msg)


def test_scale_has_no_endpoint_bias() -> None:
    width, height = 1080, 2400
    assert scale_axis(0, width) == 0
    assert scale_axis(width - 1, width) == ABS_MAX
    assert scale_axis(0, height) == 0
    assert scale_axis(height - 1, height) == ABS_MAX
    # Inclusive endpoints map the middle pixel near the HID midpoint; even
    # widths are one step above MAX/2 because pixel span-1 owns 32767.
    mid = scale_axis(width // 2, width)
    assert abs(mid - ABS_MAX // 2) <= (ABS_MAX // (width - 1)) + 1
    # Round-trip through the phone's inverse mapping stays on the same pixel.
    for px in (0, 1, width // 3, width // 2, width - 2, width - 1):
        abs_x = scale_axis(px, width)
        recovered = (abs_x * (width - 1) + ABS_MAX // 2) // ABS_MAX
        assert recovered == px, (px, abs_x, recovered)


def test_hogp_mouse_is_absolute_16bit() -> None:
    section = mouse_section(HOGP)
    if "0x81)\n    m.push(0x06)" in section or "Input (Data, Var, Rel)" in section:
        fail("mouse report still advertises relative axes")
    if "Usage (Wheel)" in section:
        fail("absolute phone pointer must not carry a relative wheel axis")
    if "Report Size (16)" not in section and "m.push(0x10)" not in section:
        fail("absolute X/Y must use 16-bit fields")
    if "32767" not in section and "0x7F" not in section:
        fail("logical maximum must be 32767")
    if "hogp_build_mouse(buttons int, dx int, dy int, wheel int)" in HOGP:
        fail("hogp_build_mouse must take absolute x/y, not relative dx/dy/wheel")
    if "HID_MOUSE_ABS_MAX" not in HOGP:
        fail("expose HID_MOUSE_ABS_MAX for host scaling")
    if "hogp_scale_axis" not in HOGP:
        fail("expose hogp_scale_axis so pixel→HID mapping is shared")


def test_att_mouse_report_is_five_bytes() -> None:
    if "mouse_value: hci_zeros(4)" in ATT:
        fail("ATT mouse value must store five absolute bytes")
    if "if handle == ATT_HANDLE_MOUSE_REPORT { expected = 4 }" in ATT:
        fail("ATT notification length must expect five absolute bytes")
    if re.search(r"handle == 0x18 \|\| handle == 0x28 \{ << 4 \}", ATT):
        fail("mouse characteristic length must be 5, not shared with HID info's 4")


def test_control_envelope_accepts_absolute_mouse() -> None:
    if "report.len == 4 && report[0] <= 7 && report[1] != 128" in CONTROL:
        fail("control still validates relative four-byte mouse reports")
    if "report.len != 5" not in CONTROL or "32767" not in CONTROL:
        fail("control must require five-byte absolute mouse reports in 0..32767")
    if "absolute" not in CONTROL_README.lower() and "32767" not in CONTROL_README:
        fail("control README must document absolute 0..32767 mouse bytes")


def test_mqtt_release_keeps_last_point() -> None:
    if "mouse_x" not in MQTT or "mouse_y" not in MQTT:
        fail("MQTT state must remember last absolute coordinates")
    if "hogp_build_mouse(0,0,0,0)" in MQTT:
        fail("releasing at (0,0) drags the phone pointer to the origin")
    if "hogp_build_mouse(0, state.mouse_x, state.mouse_y)" not in MQTT:
        fail("button release must reuse the last absolute point")
    if "hogp_build_mouse(0,1,0,0)" in TRANSPORT or "hogp_build_mouse(0,-1,0,0)" in TRANSPORT:
        fail("UART mouse probe still emits relative deltas")


def main() -> int:
    tests = [
        test_scale_has_no_endpoint_bias,
        test_hogp_mouse_is_absolute_16bit,
        test_att_mouse_report_is_five_bytes,
        test_control_envelope_accepts_absolute_mouse,
        test_mqtt_release_keeps_last_point,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"ok  {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    if failed:
        print(f"{failed} absolute-pointer contract check(s) failed")
        return 1
    print("absolute pointer contract checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
