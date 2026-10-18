#!/usr/bin/env python3
"""Validate the hosted product source closure, runtime ABI and build contract.

All checks are local to this checkout. The historical filename and
--strict-freeze/--ci options remain compatible with existing build callers.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "BOUNDARY.json"
MODULE_IMPORT_RE = re.compile(
    r"^\s*#([A-Za-z_][A-Za-z0-9_./-]*)\s*(?:$|//)", re.MULTILINE
)
class BoundaryCheck:
    def __init__(
        self, root: Path, manifest_path: Path, *, strict_freeze: bool = False, ci: bool = False
    ) -> None:
        # Canonicalise the checkout root once.  On macOS ``/tmp`` may be a
        # symlink to ``/private/tmp``; comparing an unresolved test root with
        # resolved children would otherwise report legitimate paths as
        # out-of-root.
        self.root = root.resolve()
        self.manifest_path = manifest_path.resolve()
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: dict[str, object] = {}
        self._reported_paths: set[str] = set()
        self.manifest_source_config: dict | None = None
        self.strict_freeze = strict_freeze
        self.ci = ci

    def error(self, message: str) -> None:
        self.errors.append(message)

    def error_once(self, key: str, message: str) -> None:
        """Report a path/invariant error once even when several scans see it."""

        if key in self._reported_paths:
            return
        self._reported_paths.add(key)
        self.error(message)

    def repository_root(self, path: Path) -> Path:
        """All contract paths belong to the product checkout."""
        return self.root

    def relative(self, path: Path) -> Path:
        return path.relative_to(self.root)

    def _reject_symlink_components(self, candidate: Path, label: str) -> bool:
        """Reject symlinks in a manifest path, even when they stay in ROOT.

        Resolving a symlink to an in-tree target would otherwise make a source
        manifest look stable while allowing a checkout to substitute code
        behind the declared path.  The boundary contract is deliberately
        stricter: every component must be a real directory/file owned by the
        checkout.  Out-of-root targets are reported separately by ``path``.
        """

        owner = self.root
        parts = candidate.parts
        current = owner
        unsafe = current.is_symlink()
        if unsafe:
            self.error_once(f"symlink:{current}", f"{label}: symlink is not allowed in boundary path: {candidate}")
        for part in parts:
            if part in ("", "."):
                continue
            current = current / part
            try:
                if current.is_symlink():
                    self.error_once(
                        f"symlink:{current}",
                        f"{label}: symlink is not allowed in boundary path: "
                        f"{candidate.as_posix()}",
                    )
                    unsafe = True
            except OSError as exc:
                self.error_once(
                    f"stat:{current}", f"{label}: cannot inspect {current}: {exc}"
                )
                unsafe = True
        return unsafe

    def path(self, value: str, label: str) -> Path | None:
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            self.error(f"{label}: path must be relative: {value}")
            return None
        if self._reject_symlink_components(candidate, label):
            return None
        try:
            owner = self.root
            relative = candidate
            resolved = (owner / relative).resolve()
        except RuntimeError as exc:
            self.error(f"{label}: cannot resolve path {value}: {exc}")
            return None
        try:
            resolved.relative_to(owner)
        except ValueError:
            self.error(f"{label}: path escapes repository: {value}")
            return None
        return resolved

    def regular_file(self, path: Path, label: str) -> bool:
        """Require a non-symlink regular file inside the repository."""

        try:
            path.resolve().relative_to(self.repository_root(path))
        except (OSError, RuntimeError, ValueError):
            self.error_once(
                f"outside:{path}",
                f"{label}: path escapes repository: {path}",
            )
            return False
        try:
            if path.is_symlink():
                self.error_once(
                    f"symlink:{path}",
                    f"{label}: symlink source is not allowed: "
                    f"{self.relative(path)}",
                )
                return False
            st = path.stat()
        except OSError as exc:
            self.error_once(f"stat:{path}", f"{label}: cannot stat {path}: {exc}")
            return False
        if not stat.S_ISREG(st.st_mode):
            self.error_once(
                f"nonregular:{path}",
                f"{label}: expected a regular file: {self.relative(path)}",
            )
            return False
        return True

    def source_files_under(
        self, root: Path, suffixes: tuple[str, ...], label: str, recursive: bool = True
    ) -> list[Path]:
        """List source files without following symlinks.

        ``Path.rglob`` makes it too easy to overlook a symlinked file or
        directory.  The explicit walk keeps the closure/hash reproducible and
        fail-closed if a checkout injects an alias.
        """

        try:
            root.resolve().relative_to(self.repository_root(root))
        except (OSError, RuntimeError, ValueError):
            self.error_once(
                f"outside:{root}", f"{label}: source root escapes repository: {root}"
            )
            return []
        if root.is_symlink():
            self.error_once(
                f"symlink:{root}",
                f"{label}: symlink directory is not allowed: "
                f"{self.relative(root)}",
            )
            return []
        if not root.exists():
            return []
        if not root.is_dir():
            self.error_once(
                f"notdir:{root}",
                f"{label}: expected a directory: {self.relative(root)}",
            )
            return []

        out: list[Path] = []
        # ``os.walk`` is intentionally avoided here: Path.iterdir gives us a
        # direct symlink check before any recursion and deterministic sorting.
        pending = [root]
        while pending:
            current = pending.pop()
            try:
                children = sorted(
                    current.iterdir(), key=lambda p: p.name.encode("utf-8")
                )
            except OSError as exc:
                self.error_once(
                    f"read-dir:{current}", f"{label}: cannot read {current}: {exc}"
                )
                continue
            for child in children:
                if child.is_symlink():
                    self.error_once(
                        f"symlink:{child}",
                        f"{label}: symlink source is not allowed: "
                        f"{self.relative(child)}",
                    )
                    continue
                if child.is_dir():
                    if recursive:
                        pending.append(child)
                    continue
                if child.suffix in suffixes and self.regular_file(child, label):
                    out.append(child)
        return sorted(out, key=lambda p: self.relative(p).as_posix().encode("utf-8"))

    def read(self, value: str, label: str) -> str | None:
        path = self.path(value, label)
        if path is None:
            return None
        if not self.regular_file(path, label):
            if not path.exists():
                self.error(f"{label}: file not found: {value}")
            return None
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            self.error(f"{label}: not UTF-8: {value}: {exc}")
            return None

    def check_required_paths(self, manifest: dict) -> None:
        paths = manifest.get("required_paths")
        if not isinstance(paths, list) or not paths:
            self.error("required_paths must be a non-empty list")
            return
        for index, value in enumerate(paths):
            if not isinstance(value, str):
                self.error(f"required_paths[{index}] must be a string")
                continue
            # Development docs and the sync ledger intentionally stay local.
            if self.ci and (value.startswith(("docs/", "tests/"))):
                continue
            path = self.path(value, f"required_paths[{index}]")
            if path is not None and not path.exists():
                self.error(f"required_paths[{index}]: path not found: {value}")

    def check_roles(self, manifest: dict) -> None:
        roles = manifest.get("roles")
        if not isinstance(roles, dict):
            self.error("roles must be an object")
            return
        product = roles.get("xu")
        if not isinstance(product, dict):
            self.error("roles must contain xu object")
            return
        if product.get("root") != "src" or not product.get("product_artifact"):
            self.error("xu role must be the src product authority")
        self.info["product_role"] = product.get("authority", [])

        scope = manifest.get("scope", {})
        paths = scope.get("compiler_chain") if isinstance(scope, dict) else None
        if not isinstance(paths, list) or not paths:
            self.error("scope.compiler_chain must be a non-empty list")
            return
        for index, value in enumerate(paths):
            if not isinstance(value, str):
                self.error(f"scope.compiler_chain[{index}] must be a string")
                continue
            path = self.path(value, f"scope.compiler_chain[{index}]")
            if path is not None and not path.is_dir():
                self.error(f"scope.compiler_chain[{index}]: directory not found: {value}")
        self.info["workspace_scope"] = not self.errors

    def check_generation(self, manifest: dict) -> None:
        generation = manifest.get("generation")
        if not isinstance(generation, dict):
            self.error("generation must be an object")
            return
        for stage, producer in (("gen1", "Seed"), ("gen2", "Gen1"),
                                ("gen3", "Gen2"), ("gen4", "Gen3")):
            item = generation.get(stage)
            if not isinstance(item, dict):
                self.error(f"generation.{stage} must be an object")
                continue
            for key, expected in (("producer", producer), ("output", stage.title()),
                                  ("input", "scripts/gen1_sources.sh")):
                if item.get(key) != expected:
                    self.error(f"generation.{stage}.{key} must be {expected!r}")
        self.check_profiles(manifest, generation)
        warmup = generation.get("warmup")
        if warmup is not None:
            if not isinstance(warmup, dict):
                self.error("generation.warmup must be an object")
            else:
                if warmup.get("artifact") != "Gen2":
                    self.error("generation.warmup.artifact must be Gen2")
                hops = warmup.get("max_transient_hops")
                if not isinstance(hops, int) or isinstance(hops, bool) or hops < 0:
                    self.error("generation.warmup.max_transient_hops must be a non-negative integer")
        fixed = str(generation.get("fixed_point", ""))
        if not all(marker in fixed for marker in ("byte-identical", "Gen2", "Gen3")):
            self.error("generation.fixed_point must confirm Gen2/Gen3 byte identity")
        self.info["generation_fixed_point"] = fixed


    def check_profiles(self, manifest: dict, generation: dict) -> None:
        """Validate the named optimization profiles and their generation use.

        The product chain intentionally follows compiler defaults (currently
        O1 with an automatic RA tier), while the deterministic vreg acceptance
        lane pins ``-O1 --ra=1``.  Keeping these as named profiles prevents a
        documentation-only flag change from silently making hosted generations
        different lowering policies.
        """

        profiles = manifest.get("profiles")
        if not isinstance(profiles, dict):
            self.error("profiles must be an object")
            return
        if "hosted_product" not in profiles:
            self.error("profiles.hosted_product must be present")
            return
        for name in profiles:
            item = profiles.get(name)
            if not isinstance(item, dict):
                self.error(f"profiles.{name} must be an object")
                continue
            args = item.get("args")
            if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
                self.error(f"profiles.{name}.args must be a string list")
                continue
            lane = item.get("lane")
            if not isinstance(lane, str) or not lane:
                self.error(f"profiles.{name}.lane must be non-empty")

        for stage in ("gen1", "gen2", "gen3", "gen4"):
            item = generation.get(stage)
            if not isinstance(item, dict):
                continue
            if item.get("profile") != "hosted_product":
                self.error(f"generation.{stage}.profile must be hosted_product")
            if item.get("acceptance_profile") and item.get("acceptance_profile") != "hosted_acceptance":
                self.error(
                    f"generation.{stage}.acceptance_profile must be hosted_acceptance"
                )
        self.info["profiles"] = {
            name: profiles.get(name, {}).get("args", [])
            for name in profiles
            if isinstance(profiles.get(name), dict)
        }


    def check_runtime_contract_registry(self, manifest: dict) -> None:
        config = manifest.get("runtime_contract_registry")
        expected = {"schema": 1, "registry": "src/runtime/ABI.json",
                    "generated": "src/xu/types/runtime_abi_generated.xu",
                    "generator": "scripts/generate_runtime_abi_registry.py"}
        if config != expected:
            self.error("runtime_contract_registry: unsupported or missing registry configuration")
            return
        paths = {key: self.path(config[key], "runtime_contract_registry." + key)
                 for key in ("registry", "generated", "generator")}
        if any(path is None or not self.regular_file(path, "runtime_contract_registry." + key)
               for key, path in paths.items()):
            return
        try:
            spec = importlib.util.spec_from_file_location("xu_runtime_registry_generator", paths["generator"])
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            raw = paths["registry"].read_bytes()
            expected_source = module.render(raw)
            if paths["generated"].read_text(encoding="utf-8") != expected_source:
                self.error("runtime_contract_registry: generated Xu differs from registry; regenerate it")
                return
            self.info["runtime_contract_registry"] = {
                "status": "PASS", "schema": 1,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "entries": len(module.validate(json.loads(raw))),
                "effect_authority": "declaration only; not optimization proof",
            }
        except (ValueError, KeyError, TypeError, OSError, AttributeError) as exc:
            self.error("runtime_contract_registry: " + str(exc))

    def check_runtime_abi(self, manifest: dict) -> None:
        entries = manifest.get("runtime_abi")
        if not isinstance(entries, list) or not entries:
            self.error("runtime_abi must be a non-empty list")
            return
        ids: set[str] = set()
        checked_symbols = 0
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                self.error(f"runtime_abi[{index}] must be an object")
                continue
            entry_id = entry.get("id")
            if not isinstance(entry_id, str) or not entry_id:
                self.error(f"runtime_abi[{index}].id must be non-empty")
            elif entry_id in ids:
                self.error(f"duplicate runtime ABI id: {entry_id}")
            else:
                ids.add(entry_id)

            contents: dict[str, str] = {}
            for side in ("product_paths",):
                paths = entry.get(side)
                if not isinstance(paths, list) or not paths:
                    self.error(f"runtime_abi[{index}].{side} must be a non-empty list")
                    continue
                chunks: list[str] = []
                for pindex, value in enumerate(paths):
                    if not isinstance(value, str):
                        self.error(f"runtime_abi[{index}].{side}[{pindex}] must be a string")
                        continue
                    path = self.path(value, f"runtime_abi[{index}].{side}[{pindex}]")
                    if path is None or not path.exists():
                        self.error(f"runtime_abi[{index}].{side}[{pindex}]: path not found: {value}")
                        continue
                    if path.is_file():
                        files = (
                            [path]
                            if self.regular_file(
                                path, f"runtime_abi[{index}].{side}[{pindex}]"
                            )
                            else []
                        )
                    else:
                        files = self.source_files_under(
                            path,
                            (".xu",),
                            f"runtime_abi[{index}].{side}[{pindex}]",
                            recursive=True,
                        )
                    if not files:
                        self.error(f"runtime_abi[{index}].{side}[{pindex}]: no source files: {value}")
                        continue
                    for file in files:
                        try:
                            raw = file.read_text(encoding="utf-8")
                            # A symbol must be present in executable/source
                            # text, not only in a porting note.  The Xu
                            # comment stripper is also conservative for Rust
                            # comments and leaves string literals (the actual
                            # label table) intact.
                            chunks.append(self.strip_source_comments(raw))
                        except UnicodeDecodeError as exc:
                            self.error(f"runtime ABI source is not UTF-8: {file}: {exc}")
                contents[side] = "\n".join(chunks)

            symbols = entry.get("symbols")
            if not isinstance(symbols, list) or not symbols:
                self.error(f"runtime_abi[{index}].symbols must be a non-empty list")
                continue
            for symbol in symbols:
                if not isinstance(symbol, str) or not symbol:
                    self.error(f"runtime_abi[{index}] contains an invalid symbol")
                    continue
                checked_symbols += 1
                for side in ("product_paths",):
                    if symbol not in contents.get(side, ""):
                        self.error(
                            f"runtime ABI {entry_id or index}: {symbol} missing from {side} endpoint"
                        )
        self.info["runtime_symbols_checked"] = checked_symbols

    @staticmethod
    def strip_source_comments(text: str) -> str:
        """Remove Xu // and /* */ comments while preserving line positions.

        Strings (including backtick strings) are copied verbatim, so a path in
        a diagnostic string is treated as code/data and is not silently hidden.
        """

        out: list[str] = []
        i = 0
        state = "normal"
        while i < len(text):
            ch = text[i]
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if state == "normal":
                if ch == "/" and nxt == "/":
                    out.extend((" ", " "))
                    i += 2
                    state = "line"
                    continue
                if ch == "/" and nxt == "*":
                    out.extend((" ", " "))
                    i += 2
                    state = "block"
                    continue
                if ch in ('"', "`"):
                    state = "double" if ch == '"' else "backtick"
                out.append(ch)
                i += 1
                continue
            if state == "line":
                if ch == "\n":
                    out.append(ch)
                    state = "normal"
                else:
                    out.append(" ")
                i += 1
                continue
            if state == "block":
                if ch == "*" and nxt == "/":
                    out.extend((" ", " "))
                    i += 2
                    state = "normal"
                else:
                    out.append("\n" if ch == "\n" else " ")
                    i += 1
                continue
            # String state.  Keep escapes intact; comments inside a string are
            # data, not a dependency on the primer.
            out.append(ch)
            if state == "double" and ch == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if (state == "double" and ch == '"') or (
                state == "backtick" and ch == "`"
            ):
                state = "normal"
            i += 1
        return "".join(out)

    def source_files(self) -> list[Path]:
        return self.source_files_under(self.root / "src", (".xu",), "product source")

    def check_product_source_purity(self, manifest: dict) -> None:
        invariants = manifest.get("invariants")
        if not isinstance(invariants, dict):
            self.error("invariants must be an object")
            return
        if invariants.get("product_source_must_not_import_bootstrap") is True:
            refs: list[str] = []
            for path in self.source_files():
                try:
                    source = self.strip_source_comments(path.read_text(encoding="utf-8"))
                except UnicodeDecodeError as exc:
                    self.error(f"product source is not UTF-8: {path}: {exc}")
                    continue
                for line_no, line in enumerate(source.splitlines(), 1):
                    if re.search(r"bootstrap(?:/|\\)", line) or re.match(
                        r"^\s*#bootstrap(?:[./]|\s|$)", line, re.IGNORECASE
                    ):
                        refs.append(f"{self.relative(path)}:{line_no}")
                    # Module imports are written as ``#bootstrap`` or
                    # ``#bootstrap/...`` and do not contain a slash in the
                    # first token.  Keep this check anchored at line start so
                    # ordinary identifiers/field names remain legal while a
                    # future primer import cannot slip through the path-only
                    # expression above.
            if refs:
                self.error(
                    "product Xu source has an active bootstrap path reference: "
                    + ", ".join(refs[:12])
                    + (" …" if len(refs) > 12 else "")
                )

        # A product source file may carry provenance comments and domain
        # identifiers such as ``ContentPlugin.bootstrap``.  It must not,
        # however, emit an executable instruction that sends users back to
        # the Gen0 primer.  The path check above intentionally catches
        # ``bootstrap/…`` references; this narrower phrase check closes the
        # complementary hole for strings such as ``use bootstrap xu`` while
        # leaving legitimate field names untouched.
        if invariants.get("product_source_must_not_reference_primer") is True:
            primer_refs: list[str] = []
            phrase_re = re.compile(r"\bbootstrap\s+(?:xu|primer)\b", re.IGNORECASE)
            for path in self.source_files():
                try:
                    source = self.strip_source_comments(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError):
                    continue
                for line_no, line in enumerate(source.splitlines(), 1):
                    if phrase_re.search(line):
                        primer_refs.append(f"{self.relative(path)}:{line_no}")
            if primer_refs:
                self.error(
                    "product Xu source has an active primer instruction/reference: "
                    + ", ".join(primer_refs[:12])
                    + (" …" if len(primer_refs) > 12 else "")
                )

        default_ledger = invariants.get("gen1_heap_ledger_enabled_default")
        heap_path = self.root / "src" / "cmd" / "compile" / "rt_heap_sync.xu"
        try:
            heap_source = heap_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.error(f"cannot read Gen1 heap policy: {exc}")
        else:
            declarations = re.findall(
                r"\bconst\s+gen1_heap_ledger_enabled\s*=\s*(-?\d+)\b", heap_source
            )
            if declarations != [str(default_ledger)]:
                self.error(
                    "Gen1 heap ledger default must be exactly "
                    f"const gen1_heap_ledger_enabled = {default_ledger}; got {declarations!r}"
                )
            self.info["gen1_heap_ledger_enabled"] = int(declarations[0]) if declarations else None

        forbidden_literals = ("xu830103", "19830103", "xu_mark_payload")
        for path in self.source_files():
            try:
                source = self.strip_source_comments(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            for token in forbidden_literals:
                if token in source:
                    self.error(
                        f"primer-only watermark token {token!r} appears in product source "
                        f"{self.relative(path)}"
                    )

    def check_seed_and_chain_scripts(self) -> None:
        seed_path = self.root / "scripts" / "xu_host_seed.sh"
        chain_path = self.root / "scripts" / "build_hosted_chain.sh"
        make_path = self.root / "Makefile"
        try:
            seed = seed_path.read_text(encoding="utf-8")
            chain = chain_path.read_text(encoding="utf-8")
            makefile = make_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.error(f"cannot read product chain scripts: {exc}")
            return

        seed_active = "\n".join(
            line for line in seed.splitlines() if not line.lstrip().startswith("#")
        )
        if "bin/xu" not in seed_active or "developer/bin/xu." not in seed_active:
            self.error("xu_host_seed.sh must select a hosted bin/xu or developer/bin snapshot")
        # Seed selection never builds a compiler or invokes a Rust toolchain.
        for marker, label in (
            ("select_explicit", "explicit seed path"),
            ("select_auto", "hosted auto-discovery"),
        ):
            if marker not in seed_active:
                self.error(f"xu_host_seed.sh is missing {label} guard ({marker})")
        if re.search(r"(?:^|[;&|]\s*)cargo(?:\s|$)", seed_active, re.IGNORECASE):
            self.error("xu_host_seed.sh must not invoke cargo")
        if re.search(
            r"(?im)^\s*(?:candidate|seed|compiler|xu)\s*=.*"
            r"bootstrap/target/(?:debug|release)/xu(?:\.exe)?",
            seed_active,
        ):
            self.error("xu_host_seed.sh must not hard-code a primer binary fallback")
        if not re.search(r"select_explicit\s+\"\$XU_SEED\"", seed_active):
            self.error("xu_host_seed.sh must require an explicit XU_SEED for override")

        chain_active = "\n".join(
            line for line in chain.splitlines() if not line.lstrip().startswith("#")
        )
        for pattern, label in (
            (r"(?:\$SEED|\"\$SEED\")\s+build", "Gen0/seed hop"),
            (r"(?:\$G1|\"\$G1\")\s+build", "Gen1 hop"),
            (r"(?:\$G2|\"\$G2\")\s+build", "Gen2 hop"),
            (r"(?:\$G3|\"\$G3\")\s+build", "Gen3 confirmation hop"),
            (r"cmp\s+\"\$G3\"\s+\"\$G4\"", "fixed-point cmp"),
            (r'bash\s+\./scripts/install_product_executable\.sh\s+"\$CONFIRMED"\s+"\$DEST"', "confirmed artifact install"),
        ):
            if not re.search(pattern, chain_active):
                self.error(f"build_hosted_chain.sh is missing {label}")
        installer_path = self.path("scripts/install_product_executable.sh", "atomic installer")
        if installer_path is not None and self.regular_file(installer_path, "atomic installer"):
            try:
                installer = "\n".join(line for line in installer_path.read_text(encoding="utf-8").splitlines()
                                      if not line.lstrip().startswith("#"))
            except (OSError, UnicodeDecodeError) as exc:
                self.error(f"cannot read atomic installer: {exc}")
            else:
                for marker in ('mktemp "${install_destination}.install.XXXXXX"',
                               'cp -p "$install_source" "$install_staged"',
                               'chmod +x "$install_staged"',
                               'mv -f "$install_staged" "$install_destination"'):
                    if marker not in installer:
                        self.error(f"atomic installer is missing {marker}")
        if "build_hosted_chain.sh" not in makefile or "xu_host_seed.sh" not in makefile:
            self.error("Makefile product target must use the hosted seed and build_hosted_chain.sh")
        if "XU_SOURCE_XU" not in makefile or "find -P src -type f -name '*.xu'" not in makefile:
            self.error(
                "Makefile must depend on the complete src/**/*.xu product source tree"
            )
        if "product-selfhost" not in makefile:
            self.error("Makefile must expose an explicit product-selfhost lane")
        for marker, label in (
            ('XU_SEED="$SEED_INPUT"', "seed policy delegation"),
            ('XUPATH=""', "clean XUPATH"),
            ("XU_CACHE=", "isolated XU_CACHE"),
            ("unset XUOS XUARCH", "fixed host target"),
        ):
            if marker not in chain_active:
                self.error(f"build_hosted_chain.sh is missing {label} ({marker})")
        # An explicitly enabled oracle recovery chain may write a temporary
        # Gen4 for diagnosis, but it must stop before the product install

        if "warmup transition recorded" not in chain_active:
            self.error(
                "build_hosted_chain.sh must report the Gen2 warm-up transition"
            )
        for marker in ('if cmp -s "$G2" "$G3"; then', 'CONFIRMED="$G3"',
                       'CONFIRMED="$G4"', 'GEN3_GEN4_CMP=SKIPPED'):
            if marker not in chain_active:
                self.error(f"build_hosted_chain.sh is missing adaptive confirmation ({marker})")
        self.info["chain_script"] = "hosted seed -> Gen1 -> Gen2 -> Gen3 -> cmp; Gen4 only after a transition"

    def check_profile_scripts(self, manifest: dict) -> None:
        """Ensure executable self-host lanes consume the manifest profiles.

        ``build_hosted_chain.sh`` deliberately leaves the product profile's
        argument array empty (the compiler's default O1/RA-auto policy), while
        its acceptance profile pins ``-O1 --ra=1``.  Both hosted hops must use
        one and the same array; otherwise Gen3/Gen4 byte equality could be a
        false comparison across optimization policies.
        """

        profiles = manifest.get("profiles")
        if not isinstance(profiles, dict):
            return
        product = profiles.get("hosted_product")
        acceptance = profiles.get("hosted_acceptance")
        if not isinstance(product, dict) or not isinstance(acceptance, dict):
            return
        product_args = product.get("args")
        acceptance_args = acceptance.get("args")
        if product_args != [] or acceptance_args != ["-O1", "--ra=1"]:
            return

        chain_path = self.path(
            "scripts/build_hosted_chain.sh", "profile chain script"
        )
        if chain_path is None or not self.regular_file(chain_path, "profile chain script"):
            return
        try:
            chain = chain_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.error(f"cannot read profile chain script: {exc}")
            return
        active = "\n".join(
            line for line in chain.splitlines() if not line.lstrip().startswith("#")
        )
        required_markers = (
            (r"HOSTED_PROFILE=\$\{HOSTED_PROFILE:-product\}", "default product profile"),
            (r"product\)", "product profile case"),
            (r"acceptance\)", "acceptance profile case"),
            (r"HOSTED_ARGS=\(\)", "empty product args"),
            (r"HOSTED_ARGS=\(-O1\s+--ra=1\)", "pinned acceptance args"),
            (r"hosted_profile=\$HOSTED_PROFILE", "profile provenance output"),
        )
        for pattern, label in required_markers:
            if not re.search(pattern, active):
                self.error(f"build_hosted_chain.sh is missing {label}")

        # Three hosted hops consume the shared array.  The seed hop
        # intentionally uses compiler defaults (the hosted seed is already a
        # product binary); Gen3→Gen4 runs only after a Gen2→Gen3 transition.
        hop_uses = re.findall(r'"\$[Gg][123]"\s+build\s+"\$\{HOSTED_ARGS\[@\]\}"', active)
        if len(hop_uses) != 3:
            self.error(
                "build_hosted_chain.sh must use the shared HOSTED_ARGS array on "
                f"all three hosted hops (found {len(hop_uses)})"
            )

        self.info["profile_contract"] = {
            "product": product_args,
            "acceptance": acceptance_args,
            "chain_hops_pinned": len(hop_uses) == 3,
        }


    def check_product_compiler_wrapper(self, manifest: dict) -> None:
        """Guard sibling/cross-target invocations against ambient imports.

        Once the compiler is hosted, every product consumer must pass through
        the same hermetic wrapper.  Otherwise a stale ``XUPATH``/``XU_CACHE``
        or an accidental primer path can bypass the seed seam even though the
        main self-host chain is clean.
        """

        required = manifest.get("required_paths", [])
        if "scripts/run_product_compiler.sh" not in required:
            self.error(
                "required_paths must include scripts/run_product_compiler.sh "
                "for product compiler consumers"
            )
        wrapper_path = self.path(
            "scripts/run_product_compiler.sh", "product compiler wrapper"
        )
        if wrapper_path is None or not self.regular_file(
            wrapper_path, "product compiler wrapper"
        ):
            return
        try:
            wrapper = wrapper_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.error(f"cannot read product compiler wrapper: {exc}")
            return
        active = "\n".join(
            line for line in wrapper.splitlines() if not line.lstrip().startswith("#")
        )
        for marker, label in (
            ('XU_SEED="$COMPILER_INPUT"', "canonical seed delegation"),
            ("XU_CACHE=", "isolated XU_CACHE"),
            ("HOME=", "isolated HOME"),
            ("USERPROFILE=", "isolated USERPROFILE"),
            ("unset XUOS XUARCH", "fixed target environment"),
            ("XU_PRODUCT_XUPATH", "explicit controlled package-root seam"),
            ("normalize_product_xupath", "package-root validation"),
            ("relative_to(root)", "in-repository package-root guard"),
        ):
            if marker not in active:
                self.error(f"run_product_compiler.sh is missing {label} ({marker})")
        if not re.search(r'export\s+XUPATH="\$normalized_xupath"', active):
            self.error(
                "run_product_compiler.sh must export only the validated normalized XUPATH seam"
            )
        if not re.search(r"(?:^|\n)\s*(?:exec\s+)?\"\$COMPILER\"\s+\"\$@\"", active):
            self.error("run_product_compiler.sh must invoke the resolved hosted compiler")
        for variable, label in (
            ("XU_BOOT_EXTRA", "no bootstrap extra injection"),
            ("XU_HEAP_STATS", "no heap debug injection"),
            ("XU_SEED", "no recursive seed override"),
        ):
            if not re.search(rf"\bunset\s+[^\n]*\b{re.escape(variable)}\b", active):
                self.error(
                    f"run_product_compiler.sh is missing {label} (unset {variable})"
                )

        make_path = self.path("Makefile", "product compiler wrapper callers")
        platform_path = self.path(
            "scripts/build_platform_xu.sh", "cross-target compiler wrapper caller"
        )
        for path, label in (
            (make_path, "Makefile"),
            (platform_path, "build_platform_xu.sh"),
        ):
            if path is None or not self.regular_file(path, label):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.error(f"cannot read {label}: {exc}")
                continue
            active_text = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            if "run_product_compiler.sh" not in active_text:
                self.error(f"{label} must invoke run_product_compiler.sh for product builds")
            if label == "build_platform_xu.sh":
                # The native-target branch copies the input compiler instead
                # of invoking `build`; it therefore still has to resolve and
                # classify the input before copying it into bin/platform.
                for marker, description in (
                    ("HOST_SEED_RESOLVER", "hosted seed resolver"),
                    ("xu_host_seed.sh", "canonical seed resolver call"),
                ):
                    if marker not in active_text:
                        self.error(
                            f"{label} is missing {description} ({marker})"
                        )

        consumers = manifest.get("product_consumers")
        if not isinstance(consumers, list) or not consumers:
            self.error("product_consumers must be a non-empty list")
            consumers = []
        consumer_ids: set[str] = set()
        for index, value in enumerate(consumers):
            if not isinstance(value, str):
                self.error(f"product_consumers[{index}] must be a string")
                continue
            if value in consumer_ids:
                self.error(f"product_consumers contains duplicate path: {value}")
            consumer_ids.add(value)
            path = self.path(value, f"product_consumers[{index}]")
            if path is None or not self.regular_file(
                path, f"product_consumers[{index}]"
            ):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.error(f"cannot read product consumer {value}: {exc}")
                continue
            active_text = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            if path.suffix == ".py":
                for marker, label in (
                    ("HOST_SEED_RESOLVER", "hosted seed resolver"),
                    ("PRODUCT_COMPILER_RUNNER", "hermetic product compiler runner"),
                    ("resolve_product_xu", "product compiler resolution"),
                    ("run_product_compiler", "product wrapper invocation"),
                ):
                    if marker not in active_text:
                        self.error(
                            f"product consumer {value} is missing {label} ({marker})"
                        )
                if re.search(r"\bcargo\s+build\b", active_text):
                    self.error(
                        f"product consumer {value} must not build or fall back to cargo"
                    )
                if "BOOTSTRAP_XU" in active_text or "ensure_bootstrap_xu" in active_text:
                    self.error(
                        f"product consumer {value} must not select a bootstrap primer"
                    )
            elif path.name != "run_product_compiler.sh" and "run_product_compiler.sh" not in active_text:
                self.error(
                    f"product consumer {value} must invoke run_product_compiler.sh"
                )
            self.check_product_bootstrap_reference(value, active_text)
        self.info["product_consumers"] = sorted(consumer_ids)
        self.info["product_compiler_wrapper"] = "hermetic hosted consumer seam"

        # A subset of product consumers resolves a seed itself (rather than
        # receiving one from a higher-level orchestrator).  Keep this subset
        # explicit so a future test/benchmark cannot silently restore the old
        # ``bin/xu``/bootstrap fallback while still calling the wrapper.
        seed_cfg = manifest.get("product_seed_consumers")
        if not isinstance(seed_cfg, dict):
            self.error("product_seed_consumers must be an object")
            seed_paths: list[str] = []
        else:
            if seed_cfg.get("lane") != "product":
                self.error("product_seed_consumers.lane must be product")
            if seed_cfg.get("explicit_only") is not True:
                self.error("product_seed_consumers.explicit_only must be true")
            seed_paths = seed_cfg.get("paths")
            if not isinstance(seed_paths, list) or not seed_paths:
                self.error("product_seed_consumers.paths must be a non-empty list")
                seed_paths = []
        seed_ids: set[str] = set()
        for index, value in enumerate(seed_paths):
            label = f"product_seed_consumers.paths[{index}]"
            if not isinstance(value, str):
                self.error(f"{label} must be a string")
                continue
            if value in seed_ids:
                self.error(f"product_seed_consumers.paths contains duplicate path: {value}")
            seed_ids.add(value)
            if value not in consumer_ids:
                self.error(f"product_seed_consumers path is not a product consumer: {value}")
            path = self.path(value, label)
            if path is None or not self.regular_file(path, label):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.error(f"cannot read product seed consumer {value}: {exc}")
                continue
            active = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            if not re.search(r"\bLANE\s*=\s*['\"]product['\"]", active):
                self.error(f"product seed consumer {value} is missing active LANE=product")
            for marker, label_text in (
                ("HOST_SEED_RESOLVER", "hosted seed resolver variable"),
                ("xu_host_seed.sh", "canonical seed resolver call"),
                ("PRODUCT_COMPILER_RUNNER", "product compiler runner variable"),
                ("run_product_compiler.sh", "hermetic product runner call"),
            ):
                if marker not in active:
                    self.error(f"product seed consumer {value} is missing {label_text} ({marker})")
            if re.search(r"\bcargo\s+(?:build|run|test)\b", active):
                self.error(f"product seed consumer {value} must not invoke cargo")
            self.check_product_bootstrap_reference(value, active)
        self.info["product_seed_consumers"] = sorted(seed_ids)

        # Some product-facing tools are orchestration layers rather than
        # direct compiler consumers (for example remote deployment and the
        # macOS .app wrapper).  Keep them in a separate manifest section so a
        # future refactor cannot accidentally bypass the checked consumer
        # below them while still passing the direct-consumer rules above.
        orchestrators = manifest.get("product_orchestrators")
        if not isinstance(orchestrators, list) or not orchestrators:
            self.error("product_orchestrators must be a non-empty list")
            orchestrators = []
        orchestrator_ids: set[str] = set()
        for index, entry in enumerate(orchestrators):
            if not isinstance(entry, dict):
                self.error(f"product_orchestrators[{index}] must be an object")
                continue
            value = entry.get("path")
            delegate = entry.get("delegates_to")
            lane = entry.get("lane")
            if not isinstance(value, str) or not value:
                self.error(f"product_orchestrators[{index}].path must be a string")
                continue
            if value in orchestrator_ids:
                self.error(f"product_orchestrators contains duplicate path: {value}")
            orchestrator_ids.add(value)
            if lane != "product":
                self.error(
                    f"product_orchestrators[{index}] must be lane=product (got {lane!r})"
                )
            if not isinstance(delegate, str) or not delegate:
                self.error(
                    f"product_orchestrators[{index}].delegates_to must be a string"
                )
                continue
            path = self.path(value, f"product_orchestrators[{index}]")
            delegate_path = self.path(
                delegate, f"product_orchestrators[{index}].delegates_to"
            )
            if path is None or not self.regular_file(
                path, f"product_orchestrators[{index}]"
            ):
                continue
            if delegate_path is None or not self.regular_file(
                delegate_path, f"product_orchestrators[{index}].delegates_to"
            ):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.error(f"cannot read product orchestrator {value}: {exc}")
                continue
            active_text = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            delegate_name = delegate_path.name
            if delegate_name not in active_text and delegate not in active_text:
                self.error(
                    f"product orchestrator {value} must delegate to {delegate}"
                )
            if re.search(r"\bcargo\s+build\b", active_text):
                self.error(
                    f"product orchestrator {value} must not build the primer with cargo"
                )
            if "BOOTSTRAP_XU" in active_text or "ensure_bootstrap_xu" in active_text:
                self.error(
                    f"product orchestrator {value} must not select a bootstrap primer"
                )
        self.info["product_orchestrators"] = sorted(orchestrator_ids)

    def check_product_bootstrap_reference(self, value: str, active_text: str) -> None:
        """Retired compiler paths cannot re-enter a product consumer."""
        if re.search(r"bootstrap[/\\]target|BOOTSTRAP_ROOT|--oracle", active_text):
            self.error(f"product consumer {value} references the retired compiler")
        if re.search(r"\bcargo\s+(?:build|run|test)\b", active_text):
            self.error(f"product consumer {value} must not invoke cargo")


    def check_product_probes(self, manifest: dict) -> None:
        """Check hosted diagnostics that inspect the toolchain without compiling."""

        cfg = manifest.get("product_probes")
        if not isinstance(cfg, dict):
            self.error("product_probes must be an object")
            self.info["product_probes"] = []
            return
        if cfg.get("lane") != "product":
            self.error("product_probes.lane must be product")
        if cfg.get("explicit_only") is not True:
            self.error("product_probes.explicit_only must be true")
        paths = cfg.get("paths")
        if not isinstance(paths, list) or not paths:
            self.error("product_probes.paths must be a non-empty list")
            paths = []

        product_ids = {
            value
            for value in manifest.get("product_consumers", [])
            if isinstance(value, str)
        }
        orchestrator_ids = {
            entry.get("path")
            for entry in manifest.get("product_orchestrators", [])
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        }
        seen: set[str] = set()
        for index, value in enumerate(paths):
            label = f"product_probes.paths[{index}]"
            if not isinstance(value, str):
                self.error(f"{label} must be a string")
                continue
            if value in seen:
                self.error(f"product_probes.paths contains duplicate path: {value}")
            seen.add(value)
            if value in product_ids | orchestrator_ids:
                self.error(f"product_probes path overlaps another consumer section: {value}")
            path = self.path(value, label)
            if path is None or not self.regular_file(path, label):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.error(f"cannot read product probe {value}: {exc}")
                continue
            active = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            for marker, description in (
                ("HOST_SEED_RESOLVER", "hosted seed resolver"),
            ):
                if marker not in active:
                    self.error(f"product probe {value} is missing {description} ({marker})")
            if re.search(r"\bcargo\s+(?:build|run|test)\b", active):
                self.error(f"product probe {value} must not invoke cargo")
        self.info["product_probes"] = sorted(seen)

    def check_boundary_infrastructure(self, manifest: dict) -> None:
        """Validate the small set of files that *define* the lane seam.

        Consumer inventories answer "who calls a compiler?"; this section
        answers "where is the policy implemented?".  Keeping the resolver,
        hosted chain, product wrapper, source manifest, checker, and Makefile
        registered prevents a seemingly harmless helper rename from leaving
        the executable boundary undocumented.
        """

        cfg = manifest.get("boundary_infrastructure")
        if not isinstance(cfg, dict):
            self.error("boundary_infrastructure must be an object")
            self.info["boundary_infrastructure"] = []
            return
        entries = cfg.get("paths")
        if not isinstance(entries, list) or not entries:
            self.error("boundary_infrastructure.paths must be a non-empty list")
            entries = []
        required_markers: dict[str, tuple[str, ...]] = {
            "seed-resolver": ("select_auto", "select_explicit"),
            "generation-orchestrator": (
                "HOSTED_PROFILE",
                "gen2_to_gen3",
                "gen3_to_gen4",
            ),
            "product-wrapper": (
                "XU_SEED",
                "XU_CACHE",
                "XU_PRODUCT_XUPATH",
            ),
            "policy-checker": ("strict-freeze", "BOUNDARY.json"),
            "source-manifest": ("GEN1_SRCS", "GEN1_PARSE", "LC_ALL=C sort"),
            "top-level-entrypoints": ("product-selfhost", "build_hosted_chain.sh"),
        }
        seen: set[str] = set()
        for index, entry in enumerate(entries):
            label = f"boundary_infrastructure.paths[{index}]"
            if not isinstance(entry, dict):
                self.error(f"{label} must be an object")
                continue
            value = entry.get("path")
            kind = entry.get("kind")
            lanes = entry.get("lanes")
            if not isinstance(value, str) or not value:
                self.error(f"{label}.path must be a non-empty string")
                continue
            if value in seen:
                self.error(f"boundary_infrastructure contains duplicate path: {value}")
            seen.add(value)
            if not isinstance(kind, str) or kind not in required_markers:
                self.error(
                    f"{label}.kind must be one of {sorted(required_markers)!r}"
                )
                continue
            if not isinstance(lanes, list) or not lanes or any(
                not isinstance(lane, str) or not lane for lane in lanes
            ):
                self.error(f"{label}.lanes must be a non-empty string list")
            path = self.path(value, label)
            if path is None or not self.regular_file(path, label):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.error(f"cannot read boundary infrastructure {value}: {exc}")
                continue
            active = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            for marker in required_markers[kind]:
                if marker not in active:
                    self.error(
                        f"{label} ({value}) is missing {kind} marker {marker!r}"
                    )
        rule = cfg.get("rule")
        if not isinstance(rule, str) or not rule.strip():
            self.error("boundary_infrastructure.rule must be non-empty")
        self.info["boundary_infrastructure"] = sorted(seen)

    def check_ci_lane_annotations(self) -> None:
        """All compiler workflows use the hosted product chain."""
        checked = []
        for path in sorted((self.root / ".github/workflows").glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            active = "\n".join(line for line in text.splitlines()
                               if not line.lstrip().startswith("#"))
            if re.search(r"bootstrap-checkout|rust-toolchain|rust-cache|\bcargo\s+(?:build|test|run)|XU_CI_LANE:\s*oracle", active):
                self.error(f"{self.relative(path)} references the retired compiler lane")
            checked.append(self.relative(path).as_posix())
        self.info["ci_lane_annotations"] = checked

    @staticmethod
    def c_key(path: Path, root: Path) -> bytes:
        """Approximate ``LC_ALL=C sort`` for UTF-8 relative paths."""

        return path.relative_to(root).as_posix().encode("utf-8")

    def hash_source_files(self, files: Iterable[Path]) -> str:
        digest = hashlib.sha256()
        # Callers provide an already deterministic order: seed is main-first
        # followed by manifest domains, and the closure appends C-locale sorted
        # discovered files.  Preserving that order keeps the provenance hash
        # compatible with the historical GEN1 source hash while still making
        # the complete closure explicit.
        ordered = list(files)
        for path in ordered:
            if not self.regular_file(path, "source manifest"):
                continue
            try:
                data = path.read_bytes()
            except OSError as exc:
                self.error(f"source manifest: cannot read {path}: {exc}")
                continue
            name = self.relative(path).as_posix()
            # Delimit fields explicitly so concatenations cannot alias.
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(len(data)).encode("ascii"))
            digest.update(b"\0")
            digest.update(data)
        return digest.hexdigest()

    def imported_modules(self, path: Path) -> list[str]:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.error(f"source manifest: cannot read {path}: {exc}")
            return []
        # Comments are removed before matching so documentation examples such
        # as ``// #foo`` cannot accidentally enlarge the closure.  Strings are
        # retained by the common stripper; import directives are line-start
        # syntax and therefore cannot occur inside a string literal.
        source = self.strip_source_comments(text)
        # A multiline/backtick string can contain a line beginning with '#'.
        # Mask string bodies before applying the line-oriented import grammar;
        # quoted data is not a dependency edge.
        masked: list[str] = []
        state = "normal"
        i = 0
        while i < len(source):
            ch = source[i]
            if state == "normal":
                if ch in ('"', "`"):
                    state = ch
                    masked.append(" ")
                else:
                    masked.append(ch)
                i += 1
                continue
            if ch == "\\" and state == '"' and i + 1 < len(source):
                masked.extend((" ", "\n" if source[i + 1] == "\n" else " "))
                i += 2
                continue
            if ch == state:
                state = "normal"
                masked.append(" ")
            else:
                masked.append("\n" if ch == "\n" else " ")
            i += 1
        source = "".join(masked)
        return sorted({match.group(1) for match in MODULE_IMPORT_RE.finditer(source)})

    def resolve_stdlib_module(self, module: str, root: Path) -> list[Path]:
        """Resolve a Xu module using the same directory/file convention as the driver."""

        if not module or module.startswith("."):
            return []
        try:
            root = root.resolve()
            root.relative_to(self.root)
        except (OSError, RuntimeError, ValueError):
            self.error(f"source manifest: stdlib root escapes repository: {root}")
            return []
        # Module IDs are slash-separated and must remain beneath the declared
        # stdlib root.  Reject traversal before touching the filesystem.
        module_path = Path(*module.split("/"))
        if module_path.is_absolute() or ".." in module_path.parts:
            self.error(f"source manifest: unsafe module id #{module}")
            return []
        directory = root / module_path
        if directory.is_symlink():
            self.error_once(
                f"symlink:{directory}",
                f"stdlib module #{module}: symlink path is not allowed: "
                f"{self.relative(directory)}",
            )
            return []
        if directory.is_dir():
            return self.source_files_under(
                directory,
                (".xu",),
                f"stdlib module #{module}",
                recursive=False,
            )
        file_path = directory.with_suffix(".xu")
        if file_path.is_symlink():
            self.error_once(
                f"symlink:{file_path}",
                f"stdlib module #{module}: symlink path is not allowed: "
                f"{self.relative(file_path)}",
            )
            return []
        if file_path.exists() and self.regular_file(file_path, f"stdlib module #{module}"):
            return [file_path]
        return []

    def check_source_manifest(self, manifest: dict) -> None:
        raw_config = manifest.get("source_manifest")
        if not isinstance(raw_config, dict):
            self.error("source_manifest must be an object")
            return
        config = raw_config
        source_rel = config.get("script")
        if not isinstance(source_rel, str):
            self.error("source_manifest.script must be a string")
            return
        source_script = self.path(source_rel, "source_manifest.script")
        if source_script is None or not self.regular_file(source_script, "source_manifest.script"):
            return
        try:
            script = source_script.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.error(f"cannot read {source_rel}: {exc}")
            return

        closure = config.get("closure")
        if not isinstance(closure, dict):
            self.error("source_manifest.closure must be an object")
            return
        if closure.get("kind") != "transitive-import-closure":
            self.error("source_manifest.closure.kind must be transitive-import-closure")
        if closure.get("directory_members") != "all-direct-xu":
            self.error("source_manifest.closure.directory_members must be all-direct-xu")
        if closure.get("exclude_seed") is not True:
            self.error("source_manifest.closure.exclude_seed must be true")
        extensions = closure.get("extensions")
        if extensions != [".xu"]:
            self.error("source_manifest.closure.extensions must be ['.xu']")

        domains = config.get("seed_domains")
        if not isinstance(domains, list) or not domains:
            self.error("source_manifest.seed_domains must be a non-empty list")
            return
        domain_paths: list[Path] = []
        for index, value in enumerate(domains):
            if not isinstance(value, str):
                self.error(f"source_manifest.seed_domains[{index}] must be a string")
                continue
            path = self.path(value, f"source_manifest.seed_domains[{index}]")
            if path is None:
                continue
            if not path.is_dir():
                self.error(f"source_manifest.seed_domains[{index}] is not a directory: {value}")
                continue
            domain_paths.append(path)
        if len(domain_paths) != len(domains):
            return

        main_rel = config.get("main_first")
        if not isinstance(main_rel, str):
            self.error("source_manifest.main_first must be a string")
            return
        main = self.path(main_rel, "source_manifest.main_first")
        if main is None or not self.regular_file(main, "source_manifest.main_first"):
            return

        for token in ("LC_ALL=C sort", "GEN1_SRCS=", "GEN1_PARSE="):
            if token not in script:
                self.error(f"{source_rel} is missing deterministic discovery marker: {token}")

        # Build the exact seed order advertised by gen1_sources.sh: compiler
        # main first, then the rest of that directory, followed by each Xu
        # frontend package in manifest order.
        seed: list[Path] = []
        for index, domain in enumerate(domain_paths):
            direct = self.source_files_under(
                domain,
                (".xu",),
                f"source_manifest.seed_domains[{index}]",
                recursive=False,
            )
            if domain == main.parent:
                if main not in direct:
                    self.error("source_manifest.main_first is not in the compiler seed domain")
                seed.append(main)
                seed.extend(path for path in direct if path != main)
            else:
                seed.extend(direct)
        relative_seed = [self.relative(p).as_posix() for p in seed]
        if len(relative_seed) != len(set(relative_seed)):
            self.error("Gen1 seed manifest contains duplicate paths")
        if not seed or seed[0] != main:
            self.error("Gen1 seed manifest must begin with source_manifest.main_first")

        # Keep the shell aliases in lock-step with the declared package
        # domains.  A newly split frontend package must be consciously added
        # to both places; otherwise GEN1_PARSE can silently omit it.
        for domain in domains:
            if not isinstance(domain, str):
                continue
            if domain.startswith("src/xu/"):
                package = Path(domain).name
                marker = f"GEN1_{package.upper()}="
                if marker not in script:
                    self.error(f"{source_rel} is missing {marker} package binding")

        # Resolve all #module directives reachable from the seed.  Directory
        # imports load every direct .xu member, matching driver_build.xu; the
        # queue then follows imports from each newly discovered file.  This is
        # the part omitted by a bare 130-file GEN1_SRCS count.
        stdlib_rel = config.get("stdlib_root")
        if not isinstance(stdlib_rel, str):
            self.error("source_manifest.stdlib_root must be a string")
            return
        stdlib_root = self.path(stdlib_rel, "source_manifest.stdlib_root")
        if stdlib_root is None or not stdlib_root.is_dir():
            self.error("source_manifest.stdlib_root must be an existing directory")
            return

        seed_set = set(seed)
        seen = set(seed)
        queue: deque[Path] = deque(seed)
        imported_modules: set[str] = set()
        closure_complete = True
        while queue:
            source = queue.popleft()
            for module in self.imported_modules(source):
                imported_modules.add(module)
                resolved = self.resolve_stdlib_module(module, stdlib_root)
                if not resolved:
                    closure_complete = False
                    self.error(
                        f"source manifest: cannot resolve #{module} imported by "
                        f"{self.relative(source)}"
                    )
                    continue
                if module.startswith("xu/"):
                    # Frontend modules are part of the seed, not an implicit
                    # stdlib closure.  Reaching a new ``src/xu/*`` package
                    # without declaring its domain would make GEN1_PARSE and
                    # the actual compiler input disagree.
                    omitted = [path for path in resolved if path not in seed_set]
                    if omitted:
                        closure_complete = False
                        self.error(
                            f"source manifest: #{module} resolves outside seed_domains: "
                            + ", ".join(
                                self.relative(path).as_posix()
                                for path in omitted[:8]
                            )
                            + (" …" if len(omitted) > 8 else "")
                        )
                for child in resolved:
                    if child not in seen:
                        seen.add(child)
                        queue.append(child)

        extra = sorted(
            (path for path in seen if path not in seed_set),
            key=lambda p: self.c_key(p, self.root),
        )
        all_files = seed + extra
        all_rel = [self.relative(path).as_posix() for path in all_files]
        declared_modules = config.get("stdlib_modules")
        if not isinstance(declared_modules, list) or any(
            not isinstance(item, str) for item in declared_modules
        ):
            self.error("source_manifest.stdlib_modules must be a string list")
            declared_modules = []
        actual_stdlib_modules = {
            module for module in imported_modules if not module.startswith("xu/")
        }
        if sorted(set(declared_modules)) != sorted(actual_stdlib_modules):
            self.error(
                "source_manifest.stdlib_modules does not match the transitive import closure: "
                f"declared={sorted(set(declared_modules))!r}, "
                f"actual={sorted(actual_stdlib_modules)!r}"
            )

        self.info["source_manifest"] = {
            # Keep ``files`` as a compatibility alias for old consumers, but
            # never call it a complete set; the explicit closure counts below
            # are the release/provenance fields.
            "files": len(seed),
            "seed_files": len(seed),
            "stdlib_closure_files": len(extra),
            "closure_files": len(all_files),
            "seed_sha256": self.hash_source_files(seed),
            "closure_sha256": self.hash_source_files(all_files),
            "stdlib_modules": sorted(actual_stdlib_modules),
            "main_first_required": bool(seed and seed[0] == main),
            "complete": closure_complete and not self.errors,
        }
        if len(all_rel) != len(set(all_rel)):
            self.error("source manifest closure contains duplicate paths")

        # Prefer the script's actual expansion over source-text heuristics.
        shell = shutil.which("sh")
        if shell is not None:
            command = (
                ". ./scripts/gen1_sources.sh; "
                "printf '%s\\n' \"$GEN1_SRCS\"; "
                "printf '%s\\n' \"$GEN1_PARSE\""
            )
            try:
                proc = subprocess.run(
                    [shell, "-c", command],
                    cwd=self.root,
                    env={
                        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                        "LC_ALL": "C",
                    },
                    text=True,
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                self.warnings.append(f"could not expand {source_rel}: {exc}")
            else:
                if proc.returncode != 0:
                    self.error(
                        f"{source_rel} failed during boundary expansion: "
                        + (proc.stderr.strip() or f"exit {proc.returncode}")
                    )
                else:
                    lines = proc.stdout.splitlines()
                    if len(lines) >= 2:
                        try:
                            actual_compile = shlex.split(lines[0])
                            actual_parse = shlex.split(lines[1])
                        except ValueError as exc:
                            self.error(f"{source_rel} emitted invalid shell words: {exc}")
                        else:
                            expected_compile = [
                                self.relative(p).as_posix()
                                for p in seed
                                if p.parent == main.parent
                            ]
                            expected_parse = relative_seed
                            if actual_compile != expected_compile:
                                self.error(
                                    "GEN1_SRCS expansion differs from the declared source domain "
                                    f"(got {len(actual_compile)}, want {len(expected_compile)})"
                                )
                            if actual_parse != expected_parse:
                                self.error(
                                    "GEN1_PARSE expansion differs from the seed source manifest "
                                    f"(got {len(actual_parse)}, want {len(expected_parse)})"
                                )
                    else:
                        self.error(f"{source_rel} did not emit GEN1_SRCS and GEN1_PARSE")


    def run(self, manifest: dict) -> None:
        self.check_required_paths(manifest)
        self.check_roles(manifest)
        self.check_generation(manifest)
        self.check_runtime_abi(manifest)
        self.check_runtime_contract_registry(manifest)
        self.check_product_source_purity(manifest)
        self.check_seed_and_chain_scripts()
        self.check_profile_scripts(manifest)
        self.check_product_compiler_wrapper(manifest)
        self.check_product_probes(manifest)
        self.check_boundary_infrastructure(manifest)
        self.check_ci_lane_annotations()
        self.check_source_manifest(manifest)


def load_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"boundary: cannot load {path}: {exc}")
    if not isinstance(value, dict):
        raise SystemExit("boundary: manifest root must be an object")
    if value.get("schema") != 1:
        raise SystemExit("boundary: unsupported manifest schema (want 1)")
    return value


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="product contract manifest (default: BOUNDARY.json)",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    is_ci = os.environ.get("XU_BOUNDARY_CI") == "1" or os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"
    parser.add_argument("--ci", action="store_true", default=is_ci,
                        help="compatibility option; all checks use published product sources")
    parser.add_argument(
        "--strict-freeze",
        action="store_true",
        help="compatibility option; product contract checks are always strict",
    )
    args = parser.parse_args(argv)
    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    if manifest_path.is_symlink():
        raise SystemExit("boundary: manifest path must not be a symlink")
    try:
        manifest_path = manifest_path.resolve()
    except RuntimeError as exc:
        raise SystemExit(f"boundary: cannot resolve manifest path: {exc}")
    manifest = load_manifest(manifest_path)
    check = BoundaryCheck(ROOT, manifest_path, strict_freeze=args.strict_freeze, ci=args.ci)
    check.run(manifest)
    repo_head: str | None = None
    try:
        head_proc = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        if head_proc.returncode == 0:
            repo_head = head_proc.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        repo_head = None
    source_report = check.info.get("source_manifest")
    checks = {
        "required_paths": not any("required_paths" in e for e in check.errors),
        "roles_and_scope": "workspace_scope" in check.info
        and not any("scope" in e or "role" in e for e in check.errors),
        "generation_profiles": "profiles" in check.info
        and "generation_fixed_point" in check.info,
        "source_manifest": isinstance(source_report, dict)
        and source_report.get("complete") is True,
        "runtime_abi": "runtime_symbols_checked" in check.info,
        "runtime_contract_registry": "runtime_contract_registry" in check.info,
        "product_seed_seam": "chain_script" in check.info
        and "product_compiler_wrapper" in check.info,
        "product_consumer_seam": "product_orchestrators" in check.info
        and "product_consumers" in check.info,
        "product_seed_consumer_seam": "product_seed_consumers" in check.info,
        "product_probe_seam": "product_probes" in check.info,
        "ci_lane_annotations": "ci_lane_annotations" in check.info,
    }
    report = {
        "status": "PASS" if not check.errors else "FAIL",
        "ok": not check.errors,
        "contract_version": manifest.get(
            "contract_version", f"schema-{manifest.get('schema', 'unknown')}"
        ),
        "strict_freeze": args.strict_freeze,
        "repo_head": repo_head,
        "errors": list(check.errors),
        "warnings": list(check.warnings),
        "checks": checks,
        "manifest": str(manifest_path.relative_to(ROOT))
        if manifest_path.is_relative_to(ROOT)
        else str(manifest_path),
        **check.info,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        if check.errors:
            print("Xu product contract: FAIL")
        else:
            print("Xu product contract: PASS")
        print(f"  manifest: {report['manifest']}")
        if "source_manifest" in report:
            source = report["source_manifest"]
            assert isinstance(source, dict)
            print(f"  Gen1 seed files: {source['seed_files']}")
            print(f"  stdlib closure files: {source['stdlib_closure_files']}")
            print(f"  complete source closure files: {source['closure_files']}")
            print(f"  seed sha256: {source['seed_sha256']}")
            print(f"  closure sha256: {source['closure_sha256']}")
        if "runtime_symbols_checked" in report:
            print(f"  runtime ABI symbols checked: {report['runtime_symbols_checked']}")
    for warning in check.warnings:
        print(f"boundary: warning: {warning}", file=sys.stderr)
    for error in check.errors:
        print(f"boundary: error: {error}", file=sys.stderr)
    return 1 if check.errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
