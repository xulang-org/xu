#!/usr/bin/env python3
"""Bounded XAR1 segments over stdio/attach with a real headless Screen.

Uses the screenshot smoke's product-compiler and Linux Cairo/Pango fixture.
All fixtures stay in this checkout and all process/control waits have deadlines.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from xacp_screen_marshal_smoke import Attached, frame, hello
from xacp_screenshot_smoke import build_fixture, run, scalar

ROOT = Path(__file__).resolve().parents[1]
FRAME_BYTES = 1048576

BUFFER_CHECK = r'''@main
#xacp
#ui
#ui/widgets

fn screen_bounds(s $&widgets.Screen) int {
    $limits := xacp.default_limits()
    limits.max_frame_bytes = 1024
    $nonces := xacp.new_nonce_registry(1,false)
    $session := xacp.open_session()
    session.state = xacp.STATE_OPEN
    session.permissions = xacp.PERM_UI_READ
    request := xacp.parse_frame("id: !i 1\nop: ui.record\nargs:\n  win: !i 1\n  mode: events\n  max_bytes: !i 1024\n  duration_ms: !i 200\n") or >>
    reply := xacp.dispatch_screen(&*s,$&session,&request,&limits,$&nonces) or >>
    if !reply.outcome.ok || reply.data.len + ("id: !i 1\nok: !b true\ndata:\n").len > limits.max_frame_bytes { << 11 }
    doc := xacp.parse_frame("data:\n" + reply.data) or >>
    data := doc.get(doc.root(),"data")
    bytes := doc.as_int(doc.get(data,"bytes"))
    if bytes > (limits.max_frame_bytes - 256) / 2 || bytes != doc.as_str(doc.get(data,"payload")).len ||
       doc.as_int(doc.get(data,"records")) < 2 || !doc.as_bool(doc.get(data,"truncated")) { << 12 }
    // Even an envelope too small for one record must abort and release its id.
    limits.max_frame_bytes = 128
    small := xacp.parse_frame("id: !i 2\nop: ui.record\nargs:\n  win: !i 1\n  mode: events\n") or >>
    failed := xacp.dispatch_screen(&*s,$&session,&small,&limits,$&nonces) or >>
    if failed.outcome.ok || failed.outcome.err_code != "adapter_error" || session.active_id != 0 { << 13 }
    limits.max_frame_bytes = 1024
    next := xacp.parse_frame("id: !i 3\nop: ui.record\nargs:\n  win: !i 1\n  mode: events\n") or >>
    recovered := xacp.dispatch_screen(&*s,$&session,&next,&limits,$&nonces) or >>
    if !recovered.outcome.ok || session.active_id != 0 || session.next_id != 4 { << 14 }
    << 0
}

fn overflows(b $&xacp.RecordBuffer) bool {
    _ := b.write_str("0123456789012345678901234567890123456789") or (err) { << true }
    << false
}

fn record_overflows(r $&xacp.Recorder,b $&xacp.RecordBuffer) bool {
    _ := xacp.write_record(r,b,"event","01234567890123456789") or (err) { << true }
    << false
}

fn main() int {
    limits := xacp.default_limits()
    $sink := xacp.record_buffer(32) or (err) { << 1 }
    $session := xacp.open_session()
    session.state = xacp.STATE_OPEN
    session.permissions = xacp.PERM_UI_READ
    $recorder := xacp.start_recorder($&session,1,"events",32,&limits) or (err) { << 2 }
    n := xacp.write_record($&recorder,$&sink,"event","a") or (err) { << 3 }
    before := sink.text()
    if n != before.len || recorder.bytes != n || recorder.sequence != 2 { << 4 }
    if !overflows($&sink) || !record_overflows($&recorder,$&sink) { << 5 }
    if sink.text() != before || recorder.bytes != n || recorder.sequence != 2 { << 6 }
    _ := xacp.finish_recorder($&session,$&recorder) or (err) { << 7 }
    if recorder.is_open() || session.active_id != 0 || session.next_id != 2 { << 8 }
    $next := xacp.start_recorder($&session,2,"events",32,&limits) or (err) { << 9 }
    xacp.abort_recorder($&session,$&next)
    if next.is_open() || session.active_id != 0 || session.next_id != 3 { << 10 }
    ready := ui.Event{kind: ui.EV_CANVAS_READY,window_id: 1,menu_id: "canvas_ready\t1\t1\t1",width: 640,height: 480}
    $screen := widgets.screen(&ready) or (err) { eprintln(err.msg())
        << 15 }
    result := screen_bounds($&screen) or (err) { screen.dispose()
        eprintln(err.msg())
        << 16 }
    screen.dispose()
    if result != 0 { << result }
    println("XACP record buffer/lifecycle/frame bounds: PASS")
    << 0
}
'''


def segment(response, mode, records=None, truncated=None):
    assert len(response.encode()) <= FRAME_BYTES
    assert scalar(response, "mode") == mode
    payload = scalar(response, "payload").encode()
    assert len(payload) == int(scalar(response, "bytes"))
    found, offset = [], 0
    while offset < len(payload):
        end = payload.index(b"\n", offset)
        magic, sequence, kind, size = payload[offset:end].split(b"\t")
        assert magic == b"XAR1" and int(sequence) == len(found) + 1
        assert kind == (b"event" if mode == "events" else b"frame")
        start, size = end + 1, int(size)
        body = payload[start:start + size]
        assert len(body) == size and payload[start + size:start + size + 1] == b"\n"
        found.append(body.decode())
        offset = start + size + 1
    assert offset == len(payload) and found
    assert len(found) == int(scalar(response, "records"))
    if records is not None:
        assert len(found) == records, response
    if truncated is not None:
        assert scalar(response, "truncated") == str(truncated).lower(), response
    assert "xacp-smoke-secret" not in response
    return payload, found


def record(peer, i, mode="events", extra="", error=None):
    return peer.request(frame(i, "ui.record", f"\n  win: !i 1\n  mode: {mode}" + extra), i, error)


def exercise(app, launcher):
    peer = Attached(app, launcher)
    try:
        # UI_READ alone can sample, without injecting input or mutating Screen.
        peer.request(hello(permissions=5), 1)
        payload, bodies = segment(record(peer, 2), "events", 1, False)
        assert bodies == ["state=true\twindow=1\tcanvas=1\tgeneration=1\topen=true"]
        segment(record(peer, 3), "events", 1, False)  # independent sequence 1
        segment(record(peer, 4, extra="\n  duration_ms: !i 200\n  max_records: !i 3"),
                "events", 3, True)
        _, bodies = segment(record(peer, 5, "frames"), "frames", 1, False)
        assert "redacted=true" in bodies[0] and "pixel_width=400" in bodies[0] and "pixel_height=240" in bodies[0]
        segment(record(peer, 6, "frames", "\n  duration_ms: !i 200\n  max_records: !i 2"),
                "frames", 2, True)
        segment(record(peer, 7, extra=f"\n  max_bytes: !i {len(payload)}"), "events", 1, True)
        partial, _ = segment(record(peer, 8, extra=f"\n  max_bytes: !i {len(payload) * 2 + 1}\n  duration_ms: !i 200"),
                             "events", 2, True)
        assert len(partial) == len(payload) * 2
        record(peer, 9, extra="\n  max_bytes: !i 1", error="adapter_error")
        # Failed recording must release the reservation and retain the session.
        segment(record(peer, 10), "events", 1, False)
        peer.request(frame(11, "ui.record", "\n  win: !i 2\n  mode: events"), 11, "stale_window")
        segment(record(peer, 12, extra=f"\n  max_bytes: !i {FRAME_BYTES}\n  max_records: !i 9223372036854775807"),
                "events", 1, False)
        started = time.monotonic()
        segment(record(peer, 13, extra="\n  duration_ms: !i 35"), "events", truncated=False)
        assert time.monotonic() - started < 2
        record(peer, 14, "frames", "\n  max_bytes: !i 1", "adapter_error")
        segment(record(peer, 15, "frames", "\n  duration_ms: !i 0"), "frames", 1, False)
        peer.finish()
    finally:
        peer.stop()

    # Schema failures close control, so each malformed request gets a fresh peer.
    bad = ["\n  extra: !i 1", "\n  max_bytes: !i 0", f"\n  max_bytes: !i {FRAME_BYTES + 1}",
           "\n  max_bytes: !s bad", "\n  max_records: !i 0", "\n  max_records: !i -1",
           "\n  max_records: !b true", "\n  duration_ms: !i -1", "\n  duration_ms: !i 5000",
           "\n  duration_ms: !f 1.0"]
    args = ["\n  win: !i 1\n  mode: events" + extra for extra in bad]
    args += ["\n  win: !i 1", "\n  win: !i 0\n  mode: events",
             "\n  win: !s one\n  mode: events", "\n  win: !i 1\n  mode: invalid"]
    for arg in args:
        peer = Attached(app, launcher)
        try:
            peer.request(hello(), 1)
            peer.request(frame(2, "ui.record", arg), 2, "schema_error")
            peer.finish()
        finally:
            peer.stop()

    peer = Attached(app, launcher, mode="unregistered")
    try:
        peer.request(hello(), 1)
        record(peer, 2, error="not_implemented")
        peer.finish()
    finally:
        peer.stop()
    peer = Attached(app, launcher)
    try:
        peer.request(hello(permissions=1), 1)
        record(peer, 2, error="permission_denied")
        peer.request(frame(2, "proc.status"), 2)
        peer.finish()
    finally:
        peer.stop()

    # Configured limits must reach the UI owner as well as the transport.
    peer = Attached(app, launcher, timeout_ms="100")
    try:
        peer.request(hello(), 1)
        segment(record(peer, 2, extra="\n  duration_ms: !i 30"), "events")
        peer.request(frame(3, "proc.status"), 3)
        record(peer, 4, extra="\n  duration_ms: !i 100", error="schema_error")
        peer.finish()
    finally:
        peer.stop()
    peer = Attached(app, launcher, timeout_ms="50", no_poll=True)
    try:
        peer.request(hello(), 1)
        record(peer, 2, error="request_timeout")
        peer.request(frame(3, "proc.status"), 3)
        peer.finish()
    finally:
        peer.stop()
    peer = Attached(app, launcher, timeout_ms="6000")
    try:
        peer.request(hello(), 1)
        segment(record(peer, 2, extra="\n  duration_ms: !i 5001\n  max_records: !i 1"), "events", 1, True)
        peer.finish()
    finally:
        peer.stop()
    print(f"XACP ui.record ({'stdio' if launcher is None else 'attach'}): PASS", flush=True)


def main():
    if not sys.platform.startswith("linux"):
        print("XACP ui.record smoke: SKIP (fixture uses Linux Cairo/Pango host)")
        return
    xu = Path(os.environ.get("XU", ROOT / "bin/xu")).resolve()
    tool = xu.with_name("xu-xacp" + xu.suffix)
    with tempfile.TemporaryDirectory(prefix=".xacp-ui-record-", dir=ROOT) as tmp:
        directory = Path(tmp)
        source, core = directory / "buffer.xu", directory / "buffer"
        source.write_text(BUFFER_CHECK)
        run([ROOT / "scripts/run_product_compiler.sh", xu, "build", source, "-o", core])
        result = subprocess.run([str(core)], cwd=ROOT, env=dict(os.environ, XU_UI_SIM="1"),
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0 and not result.stderr, result
        print(result.stdout, end="", flush=True)
        app = build_fixture(xu, directory)
        for launcher in (None, tool):
            exercise(app, launcher)


if __name__ == "__main__":
    main()
