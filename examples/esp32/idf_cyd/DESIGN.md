# Design: official IDF static libraries for phone control

Approved delivery path (2026-11-05):

- Link Espressif BT/Wi-Fi static libraries via ESP-IDF **v5.3.2**.
- Keep MQTT envelope + absolute mouse `0..32767`; release at last point.
- Soft app size gate **≤ 1.5 MiB** (measured build ≈ 1.01 MiB).
- Pure-Xu `status_demo` remains experimental.

Full agent plan/spec copies also live under local `docs/superpowers/` when that
tree is present on a workstation; this file is the in-repo design anchor.
