#!/usr/bin/env python3
"""Render XU UI morph: 60fps, 4 subframes + ffmpeg tmix, bed+SFX mix."""
from __future__ import annotations

import json
import math
import subprocess
import wave
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright
from PIL import Image

ROOT = Path("/tmp/xu-ui")
ART = Path("/opt/cursor/artifacts/xu-ui-morph")
FRAMES = ROOT / "frames" / "full"
OUT = ROOT / "out"
FPS = 60
SUBS = 4


def load_wav(path: Path, sr: int = 44100) -> np.ndarray:
    out = ROOT / "audio" / "_sfx_tmp.wav"
    subprocess.check_call(
        ["ffmpeg", "-y", "-i", str(path), "-ac", "1", "-ar", str(sr), str(out)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    with wave.open(str(out), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return x


def mix_audio(period: float, duration: float, out_wav: Path):
    sr = 44100
    bed = load_wav(ROOT / "audio" / "bed_loop.wav", sr)
    n = int(round(duration * sr))
    mix = np.zeros(n, dtype=np.float32)
    mix[: min(n, len(bed))] += bed[:n] * 0.72

    def place(name: str, t: float, gain: float = 0.9):
        s = load_wav(ROOT / "sfx" / f"{name}.wav", sr) * gain
        i0 = int(t * sr)
        i1 = min(n, i0 + len(s))
        if i0 < n:
            mix[i0:i1] += s[: i1 - i0]

    # UI sounds on measured beat peaks
    place("click", 1 * period, 1.0)
    place("whoosh", 2 * period, 0.55)
    place("check", 4 * period, 0.95)
    place("whoosh", 6 * period, 0.5)
    place("click", 9 * period, 0.85)
    # scrub ticks during drag
    for k in range(6):
        place("scrub", 10 * period + k * (period / 6), 0.35)
    place("whoosh", 11 * period, 0.45)
    place("toggle", 14 * period, 1.0)
    place("whoosh", 15 * period, 0.45)
    place("whoosh", 17 * period, 0.5)
    place("whoosh", 20 * period, 0.5)
    for k in range(6):
        place("key", 21 * period + k * (period / 6.2), 0.55)
    place("click", 22 * period, 0.9)
    place("toast", 23 * period, 1.0)
    place("whoosh", 25 * period, 0.55)

    peak = np.max(np.abs(mix)) + 1e-9
    if peak > 0.98:
        mix *= 0.98 / peak
    with wave.open(str(out_wav), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())


def main():
    ART.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    if FRAMES.exists():
        for p in FRAMES.glob("*.png"):
            p.unlink()
    FRAMES.mkdir(parents=True, exist_ok=True)

    meta = json.loads((ROOT / "beats.json").read_text())
    period = meta["period"]
    duration = meta["duration"]
    nframes = int(round(duration * FPS))
    print(f"render {nframes} frames @ {FPS}fps, {SUBS} subs, dur={duration:.3f}s")

    audio_wav = OUT / "mix.wav"
    mix_audio(period, duration, audio_wav)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1440}, device_scale_factor=1)
        page.goto(f"file://{ROOT / 'index.html'}", wait_until="load")
        # disable any CSS that could blur under scale
        page.evaluate("() => { document.body.style.imageRendering = 'auto'; }")

        for fi in range(nframes):
            # 4 subframes across the frame duration, average for motion blur
            acc = None
            for s in range(SUBS):
                t = (fi + (s + 0.5) / SUBS) / FPS
                if t >= duration:
                    t = t - duration  # loop continuity for last frame blend
                page.evaluate(f"window.seek({t})")
                png = page.screenshot(type="png")
                im = Image.open(__import__("io").BytesIO(png)).convert("RGB")
                arr = np.asarray(im, dtype=np.float32)
                acc = arr if acc is None else acc + arr
            avg = (acc / SUBS).clip(0, 255).astype(np.uint8)
            Image.fromarray(avg).save(FRAMES / f"f{fi:05d}.png")
            if fi % 60 == 0:
                print(f"  {fi}/{nframes}")

        # verify loop: frame 0 vs last seek near duration
        page.evaluate("window.seek(0)")
        a = page.screenshot(type="png")
        page.evaluate(f"window.seek({duration - 1e-6})")
        b = page.screenshot(type="png")
        (OUT / "loop_start.png").write_bytes(a)
        (OUT / "loop_end.png").write_bytes(b)
        browser.close()

    nov = OUT / "nov.mp4"
    subprocess.check_call(
        [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", str(FRAMES / "f%05d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", "15", "-preset", "medium",
            str(nov),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Extra tmix pass for smoother blur (span=2 on already averaged subs)
    blurred = OUT / "blur.mp4"
    subprocess.check_call(
        [
            "ffmpeg", "-y", "-i", str(nov),
            "-vf", "tmix=frames=2:weights=1 1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "15", "-preset", "medium",
            str(blurred),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    final = OUT / "xu-ui-morph.mp4"
    subprocess.check_call(
        [
            "ffmpeg", "-y",
            "-i", str(blurred),
            "-i", str(audio_wav),
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart",
            str(final),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    dest = ART / "xu-ui-morph.mp4"
    dest.write_bytes(final.read_bytes())
    (ART / "recording_demo.mp4").write_bytes(final.read_bytes())
    # also top-level artifacts
    Path("/opt/cursor/artifacts/xu-ui-morph.mp4").write_bytes(final.read_bytes())
    print("wrote", dest, dest.stat().st_size)

    # loop RMS diff
    from PIL import Image as I
    import io
    im1 = np.asarray(I.open(io.BytesIO((OUT / "loop_start.png").read_bytes())).convert("RGB"), dtype=np.float32)
    im2 = np.asarray(I.open(io.BytesIO((OUT / "loop_end.png").read_bytes())).convert("RGB"), dtype=np.float32)
    print("loop MAE", float(np.mean(np.abs(im1 - im2))))


if __name__ == "__main__":
    main()
