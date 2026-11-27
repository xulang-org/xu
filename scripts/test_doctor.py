#!/usr/bin/env python3
"""Tests for `xu-doctor` (SDK integrity, desktop toolchains, mobile phone targets, JSON & strict)."""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
XU_DOCTOR = ROOT / "bin" / ("xu-doctor.exe" if sys.platform.startswith("win") else "xu-doctor")
XU_BIN = ROOT / "bin" / ("xu.exe" if sys.platform.startswith("win") else "xu")


def run_doc(args: list[str], extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(XU_DOCTOR), *args],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def make_fake_android_sdk(base: pathlib.Path, *, include_llvm_readelf: bool = True, jdk_version: str = "17.0.10") -> dict[str, str]:
    android_home = base / "android_sdk"
    (android_home / "platforms" / "android-35").mkdir(parents=True, exist_ok=True)
    (android_home / "platforms" / "android-35" / "android.jar").write_bytes(b"jar")

    bt = android_home / "build-tools" / "35.0.0"
    bt.mkdir(parents=True, exist_ok=True)
    for name in ("aapt2", "d8", "zipalign", "apksigner"):
        p = bt / name
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(0o755)

    cm = android_home / "cmake" / "3.22.1" / "bin"
    cm.mkdir(parents=True, exist_ok=True)
    for name in ("cmake", "ninja"):
        p = cm / name
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(0o755)

    ndk = android_home / "ndk" / "27.2.12479018"
    (ndk / "build" / "cmake").mkdir(parents=True, exist_ok=True)
    (ndk / "build" / "cmake" / "android.toolchain.cmake").write_text("# toolchain\n")
    if include_llvm_readelf:
        tag = "darwin-x86_64" if sys.platform == "darwin" else ("windows-x86_64" if sys.platform.startswith("win") else "linux-x86_64")
        re_dir = ndk / "toolchains" / "llvm" / "prebuilt" / tag / "bin"
        re_dir.mkdir(parents=True, exist_ok=True)
        re_bin = re_dir / "llvm-readelf"
        re_bin.write_text("#!/bin/sh\nexit 0\n")
        re_bin.chmod(0o755)

    java_home = base / "jdk"
    (java_home / "bin").mkdir(parents=True, exist_ok=True)
    javac = java_home / "bin" / "javac"
    javac.write_text(f"#!/bin/sh\necho 'javac {jdk_version}'\n")
    javac.chmod(0o755)
    for name in ("jar", "keytool"):
        p = java_home / "bin" / name
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(0o755)

    return {
        "ANDROID_HOME": str(android_home),
        "ANDROID_NDK_HOME": str(ndk),
        "JAVA_HOME": str(java_home),
    }


def make_fake_sdl_dir(base: pathlib.Path, major: int = 3, minor: int = 4, micro: int = 14) -> pathlib.Path:
    sdl = base / f"sdl-{major}.{minor}.{micro}"
    (sdl / "include" / "SDL3").mkdir(parents=True, exist_ok=True)
    (sdl / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.16)\n")
    (sdl / "include" / "SDL3" / "SDL_version.h").write_text(
        f"#define SDL_MAJOR_VERSION {major}\n"
        f"#define SDL_MINOR_VERSION {minor}\n"
        f"#define SDL_MICRO_VERSION {micro}\n"
    )
    return sdl


class TestXuDoctor(unittest.TestCase):
    def test_installed_sdk_root_line_compat(self) -> None:
        target = "macos-arm64" if sys.platform == "darwin" else ("windows-x64" if sys.platform.startswith("win") else "linux-x64")
        res = run_doc(["--target", target])
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        match = re.search(r"(?m)^  \[ok\]\s+Xu SDK root\s+(.+)$", res.stdout)
        self.assertIsNotNone(match, res.stdout)
        self.assertEqual(pathlib.Path(match.group(1).strip()).resolve(), ROOT.resolve())

    def test_xu_doctor_via_xu_driver_and_help(self) -> None:
        h = run_doc(["--help"])
        self.assertEqual(h.returncode, 0)
        for flag in ("--sdk", "--desktop", "--phone", "--all", "--phone-profile", "--json", "--strict", "--verbose"):
            self.assertIn(flag, h.stdout)
        via_xu = subprocess.run([str(XU_BIN), "doctor", "--sdk", "--json"], cwd=str(ROOT), capture_output=True, text=True, check=False)
        self.assertIn(via_xu.returncode, (0, 1))
        data = json.loads(via_xu.stdout)
        self.assertEqual(data["mode"], "sdk")

    def test_sdk_mode_json_and_verbose(self) -> None:
        bin_dir = str((ROOT / "bin").resolve())
        res = run_doc(["--sdk", "--verbose", "--json"], extra_env={"PATH": bin_dir + os.pathsep + os.environ.get("PATH", ""), "XU_ROOT": ""})
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        data = json.loads(res.stdout)
        self.assertTrue(data["passed"], data)
        self.assertEqual(data["mode"], "sdk")
        self.assertEqual(pathlib.Path(data["sdk_root"]).resolve(), ROOT.resolve())
        self.assertEqual(data["summary"]["missing"], 0)
        names = {c["name"] for c in data["checks"]}
        self.assertIn("Xu SDK root", names)
        self.assertIn("xu compiler", names)
        self.assertIn("SDK stdlib/host dirs", names)
        for tool in ("xu-desktop", "xu-phone", "xu-fmt", "xu-doc", "xu-map", "xu-lsp", "xu-native", "xu-setup", "xu-update", "xu-xacp"):
            self.assertIn(tool, names)

    def test_strict_fails_on_warnings(self) -> None:
        # Missing PATH xu or mismatched XU_ROOT triggers warn; --strict must fail.
        res = run_doc(["--sdk", "--strict", "--json"], extra_env={"XU_ROOT": "/nonexistent/xu-sdk-root"})
        self.assertEqual(res.returncode, 1, res.stdout)
        data = json.loads(res.stdout)
        self.assertFalse(data["passed"])
        self.assertGreater(data["summary"]["warn"], 0)

    def test_default_all_mode_json_structure(self) -> None:
        res = run_doc(["--json"])
        data = json.loads(res.stdout)
        self.assertEqual(data["mode"], "all")
        self.assertIn("summary", data)
        self.assertIsInstance(data["checks"], list)
        cats = {c["category"] for c in data["checks"]}
        self.assertIn("sdk", cats)
        self.assertIn("phone-sdk", cats)
        self.assertIn("android-arm64", cats)

    def test_phone_game_simulator_rejected(self) -> None:
        res = run_doc(["--target", "ios-simulator-arm64", "--phone-profile", "game", "--json"])
        self.assertEqual(res.returncode, 1)
        data = json.loads(res.stdout)
        self.assertFalse(data["passed"])
        self.assertGreater(data["summary"]["missing"], 0)

    def test_android_mock_sdk_ui_and_game(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xu-doc-android-") as td:
            base = pathlib.Path(td)
            env_ui = make_fake_android_sdk(base, include_llvm_readelf=True, jdk_version="17.0.10")
            env_ui["XU_PHONE_SDL_SOURCE"] = ""
            res_ui = run_doc(["--target", "android-arm64", "--phone-profile", "ui", "--json"], extra_env=env_ui)
            data_ui = json.loads(res_ui.stdout)
            self.assertEqual(res_ui.returncode, 0, data_ui)
            self.assertTrue(data_ui["passed"], data_ui)

            # Game profile without XU_PHONE_SDL_SOURCE must fail
            res_no_sdl = run_doc(["--target", "android-arm64", "--phone-profile", "game", "--json"], extra_env=env_ui)
            self.assertEqual(res_no_sdl.returncode, 1)

            # Wrong SDL version must fail
            bad_sdl = make_fake_sdl_dir(base, 3, 2, 0)
            env_bad_sdl = dict(env_ui, XU_PHONE_SDL_SOURCE=str(bad_sdl))
            res_bad_sdl = run_doc(["--target", "android-arm64", "--phone-profile", "game", "--json"], extra_env=env_bad_sdl)
            self.assertEqual(res_bad_sdl.returncode, 1)

            # Correct SDL 3.4.14 must pass
            good_sdl = make_fake_sdl_dir(base, 3, 4, 14)
            env_good_sdl = dict(env_ui, XU_PHONE_SDL_SOURCE=str(good_sdl))
            res_good_sdl = run_doc(["--target", "android-arm64", "--phone-profile", "game", "--json"], extra_env=env_good_sdl)
            data_good = json.loads(res_good_sdl.stdout)
            self.assertEqual(res_good_sdl.returncode, 0, data_good)
            self.assertTrue(data_good["passed"], data_good)

            # Old JDK 11 must fail
            env_old_jdk = make_fake_android_sdk(base / "oldjdk", jdk_version="11.0.20")
            res_old_jdk = run_doc(["--target", "android-arm64", "--phone-profile", "ui", "--json"], extra_env=env_old_jdk)
            self.assertEqual(res_old_jdk.returncode, 1)

    def test_webview_flag_compat(self) -> None:
        if sys.platform == "darwin":
            res = run_doc(["--target", "macos-arm64", "--webview", "--json"])
            self.assertEqual(res.returncode, 0, res.stdout)
            data = json.loads(res.stdout)
            self.assertEqual(data["schema_version"], 1)
            self.assertTrue(any(c["name"] == "webview" and c["status"] == "ok" for c in data["checks"]))

    def test_version_quiet_and_flag_composition(self) -> None:
        v = run_doc(["--version"])
        self.assertEqual(v.returncode, 0)
        self.assertIn("xu-doctor", v.stdout)

        # --phone-profile game alone should infer --phone mode
        gp = run_doc(["--phone-profile", "game", "--json"], extra_env={"XU_PHONE_SDL_SOURCE": ""})
        self.assertEqual(gp.returncode, 1)
        gp_data = json.loads(gp.stdout)
        self.assertEqual(gp_data["schema_version"], 1)
        self.assertEqual(gp_data["mode"], "phone")
        # XU_PHONE_SDL_SOURCE should be checked once in phone-all mode (not duplicated)
        sdl_checks = [c for c in gp_data["checks"] if c["name"] == "XU_PHONE_SDL_SOURCE"]
        self.assertEqual(len(sdl_checks), 1, sdl_checks)

        # --sdk --phone combines both sections
        sp = run_doc(["--sdk", "--phone", "--json"])
        sp_data = json.loads(sp.stdout)
        self.assertEqual(sp_data["mode"], "custom")
        cats = {c["category"] for c in sp_data["checks"]}
        self.assertIn("sdk", cats)
        self.assertIn("android-arm64", cats)

        # --quiet omits [ok] and [skip] lines while retaining Summary and warnings
        q = run_doc(["--sdk", "--quiet"], extra_env={"XU_ROOT": "/nonexistent/xu-sdk-root"})
        self.assertEqual(q.returncode, 0)
        self.assertNotIn("[ok]", q.stdout)
        self.assertIn("[warn]", q.stdout)
        self.assertIn("Summary:", q.stdout)

        # Unknown --target prints valid targets
        bad = run_doc(["--target", "atari-2600"])
        self.assertEqual(bad.returncode, 1)
        self.assertIn("macos-arm64", bad.stderr)
        self.assertIn("android-arm64", bad.stderr)

    def test_android_sdk_root_hint_and_workspace_xun_mismatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xu-doc-ws-") as td:
            base = pathlib.Path(td)
            # ANDROID_SDK_ROOT fallback hint when ANDROID_HOME is unset
            sdk_dir = base / "sdk_root"
            sdk_dir.mkdir()
            res_sdk = run_doc(
                ["--target", "android-arm64", "--json"],
                extra_env={"ANDROID_HOME": "", "ANDROID_SDK_ROOT": str(sdk_dir), "JAVA_HOME": ""},
            )
            self.assertEqual(res_sdk.returncode, 1)
            data_sdk = json.loads(res_sdk.stdout)
            ah = [c for c in data_sdk["checks"] if c["name"] == "ANDROID_HOME"][0]
            self.assertIn("ANDROID_SDK_ROOT", ah["detail"])

            # Workspace xu.xun mismatch check
            ws = base / "ws"
            ws.mkdir()
            (ws / "xu.xun").write_text("module: demo/app\nversion: !ver 0.1.0\nxu: !ver 0.0.1\n")
            res_ws = subprocess.run(
                [str(XU_DOCTOR), "--sdk", "--json"],
                cwd=str(ws),
                capture_output=True,
                text=True,
                check=False,
            )
            ws_data = json.loads(res_ws.stdout)
            xun_checks = [c for c in ws_data["checks"] if c["name"] == "workspace xu.xun"]
            self.assertEqual(len(xun_checks), 1, ws_data["checks"])
            self.assertEqual(xun_checks[0]["status"], "warn")


if __name__ == "__main__":
    unittest.main()
