#!/usr/bin/env python3
"""Check the static part of the bootstrap/Xu self-host boundary.

This is deliberately a schema/source check, not a substitute for compiling
the chain.  It verifies that the two implementations remain in their
declared roles, that the small ABI seam has both endpoints, and that the
product source does not acquire a runtime dependency on the Rust primer.
Semantic parity is covered by the oracle and self-host gates.  Ordinary mode
warns about untracked bootstrap implementation files; ``--strict-freeze``
requires every such file to be registered as an oracle/auxiliary exception.
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

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None  # type: ignore[assignment]


from companion_repos import project_root

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = project_root("bootstrap") / "BOUNDARY.json"
MODULE_IMPORT_RE = re.compile(
    r"^\s*#([A-Za-z_][A-Za-z0-9_./-]*)\s*(?:$|//)", re.MULTILINE
)
STATUS_VALUES = {
    "open",
    "cleared",
    "accepted",
    "deferred-1.0",
    "deferred-2.0",
}


class BoundaryCheck:
    def __init__(
        self, root: Path, manifest_path: Path, *, strict_freeze: bool = False, ci: bool = False
    ) -> None:
        # Canonicalise the checkout root once.  On macOS ``/tmp`` may be a
        # symlink to ``/private/tmp``; comparing an unresolved test root with
        # resolved children would otherwise report legitimate paths as
        # out-of-root.
        self.root = root.resolve()
        self.bootstrap_root = project_root("bootstrap", core_root=self.root)
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
        """Identify the owner using lexical paths, before resolving symlinks."""
        if path.is_relative_to(self.bootstrap_root):
            return self.bootstrap_root
        return self.root

    def relative(self, path: Path) -> Path:
        """Keep manifest identities stable across the two independent repos."""
        if path.is_relative_to(self.bootstrap_root):
            return Path("bootstrap") / path.relative_to(self.bootstrap_root)
        return path.relative_to(self.root)

    def _reject_symlink_components(self, candidate: Path, label: str) -> bool:
        """Reject symlinks in a manifest path, even when they stay in ROOT.

        Resolving a symlink to an in-tree target would otherwise make a source
        manifest look stable while allowing a checkout to substitute code
        behind the declared path.  The boundary contract is deliberately
        stricter: every component must be a real directory/file owned by the
        checkout.  Out-of-root targets are reported separately by ``path``.
        """

        owner = self.bootstrap_root if candidate.parts[:1] == ("bootstrap",) else self.root
        parts = candidate.parts[1:] if owner == self.bootstrap_root else candidate.parts
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
            owner = self.bootstrap_root if candidate.parts[:1] == ("bootstrap",) else self.root
            relative = Path(*candidate.parts[1:]) if owner == self.bootstrap_root else candidate
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
            if self.ci and (value.startswith(("docs/", "tests/")) or value == "bootstrap/SYNC_DIFF.md"):
                continue
            path = self.path(value, f"required_paths[{index}]")
            if path is not None and not path.exists():
                self.error(f"required_paths[{index}]: path not found: {value}")

    def check_roles(self, manifest: dict) -> None:
        roles = manifest.get("roles")
        if not isinstance(roles, dict):
            self.error("roles must be an object")
            return
        bootstrap = roles.get("bootstrap")
        product = roles.get("xu")
        if not isinstance(bootstrap, dict) or not isinstance(product, dict):
            self.error("roles must contain bootstrap and xu objects")
            return
        if bootstrap.get("root") != "bootstrap" or bootstrap.get("stage") != "Gen0":
            self.error("bootstrap role must be root=bootstrap, stage=Gen0")
        if product.get("root") != "src" or not product.get("product_artifact"):
            self.error("xu role must be the src product authority")
        if bootstrap.get("product_artifact") is not False:
            self.error("bootstrap role must not be marked as a product artifact")
        self.info["bootstrap_role"] = bootstrap.get("authority", [])
        self.info["product_role"] = product.get("authority", [])

        scope = manifest.get("scope")
        if not isinstance(scope, dict):
            self.error("scope must be an object")
            return
        compiler_chain = scope.get("compiler_chain")
        auxiliary = scope.get("auxiliary_bootstrap_consumers")
        if not isinstance(compiler_chain, list) or not compiler_chain:
            self.error("scope.compiler_chain must be a non-empty list")
        else:
            for index, value in enumerate(compiler_chain):
                if not isinstance(value, str):
                    self.error(f"scope.compiler_chain[{index}] must be a string")
                    continue
                path = self.path(value, f"scope.compiler_chain[{index}]")
                if path is not None and not path.exists():
                    self.error(f"scope.compiler_chain[{index}]: path not found: {value}")
        if not isinstance(auxiliary, list):
            self.error("scope.auxiliary_bootstrap_consumers must be a list")
        else:
            for index, value in enumerate(auxiliary):
                if not isinstance(value, str):
                    self.error(f"scope.auxiliary_bootstrap_consumers[{index}] must be a string")
                    continue
                path = self.path(value, f"scope.auxiliary_bootstrap_consumers[{index}]")
                if path is not None and not path.exists():
                    self.error(
                        f"scope.auxiliary_bootstrap_consumers[{index}]: path not found: {value}"
                    )
            self.info["auxiliary_consumers"] = auxiliary
        self.check_workspace_scope(manifest)

    def check_workspace_scope(self, manifest: dict) -> None:
        """Keep the declared compiler crate scope closed over Cargo members.

        A partial list (for example only ``xu``/``xuhir``/``xumir``) can make
        a Rust-only test look like a complete primer check while transitive
        crates such as ``xuparse`` or ``xuvm`` change underneath it.  The
        manifest therefore names compiler and auxiliary members separately and
        requires their union to equal ``bootstrap/Cargo.toml`` exactly.
        """

        scope = manifest.get("scope")
        if not isinstance(scope, dict):
            return
        config = scope.get("bootstrap_workspace")
        if not isinstance(config, dict):
            self.error("scope.bootstrap_workspace must be an object")
            return
        cargo_rel = config.get("manifest")
        if not isinstance(cargo_rel, str):
            self.error("scope.bootstrap_workspace.manifest must be a string")
            return
        cargo_path = self.path(cargo_rel, "scope.bootstrap_workspace.manifest")
        if cargo_path is None or not self.regular_file(
            cargo_path, "scope.bootstrap_workspace.manifest"
        ):
            return
        try:
            cargo_text = cargo_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.error(f"cannot read workspace manifest: {exc}")
            return

        members: list[str] = []
        if tomllib is not None:
            try:
                cargo = tomllib.loads(cargo_text)
                raw_members = cargo.get("workspace", {}).get("members", [])
                if isinstance(raw_members, list):
                    members = [str(item) for item in raw_members if isinstance(item, str)]
            except (tomllib.TOMLDecodeError, AttributeError) as exc:
                self.error(f"cannot parse bootstrap/Cargo.toml: {exc}")
                return
        else:  # pragma: no cover - only Python 3.10 without tomllib
            match = re.search(r"(?ms)^\s*members\s*=\s*\[(.*?)\]", cargo_text)
            if match:
                members = re.findall(r'"([^"]+)"', match.group(1))
            else:
                self.error("cannot locate workspace members in bootstrap/Cargo.toml")
                return

        if not members:
            self.error("bootstrap/Cargo.toml workspace.members is empty")
            return
        if any(Path(member).is_absolute() or ".." in Path(member).parts for member in members):
            self.error("bootstrap/Cargo.toml contains an unsafe workspace member path")
            return

        compiler_members = config.get("compiler_members")
        auxiliary_members = config.get("auxiliary_members")
        if not isinstance(compiler_members, list) or not compiler_members:
            self.error("scope.bootstrap_workspace.compiler_members must be non-empty")
            return
        if not isinstance(auxiliary_members, list):
            self.error("scope.bootstrap_workspace.auxiliary_members must be a list")
            return
        compiler_names = [item for item in compiler_members if isinstance(item, str)]
        auxiliary_names = [item for item in auxiliary_members if isinstance(item, str)]
        if len(compiler_names) != len(compiler_members):
            self.error("scope.bootstrap_workspace.compiler_members entries must be strings")
        if len(auxiliary_names) != len(auxiliary_members):
            self.error("scope.bootstrap_workspace.auxiliary_members entries must be strings")
        declared_names = compiler_names + auxiliary_names
        if len(declared_names) != len(set(declared_names)):
            self.error("scope.bootstrap_workspace has duplicate crate names")

        # Cargo members are paths; turn each into its package name so the
        # manifest remains stable if a member path is ever relocated.
        cargo_names: list[str] = []
        for member in members:
            member_path = self.path(
                str((Path(cargo_rel).parent / member).as_posix()),
                f"bootstrap workspace member {member}",
            )
            if member_path is None or not member_path.is_dir():
                self.error(f"workspace member directory missing: {member}")
                continue
            package_toml = member_path / "Cargo.toml"
            if not self.regular_file(package_toml, f"workspace member {member}"):
                continue
            try:
                package_text = package_toml.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.error(f"cannot read workspace member {member}: {exc}")
                continue
            package_name: str | None = None
            if tomllib is not None:
                try:
                    package = tomllib.loads(package_text).get("package", {})
                    if isinstance(package, dict) and isinstance(package.get("name"), str):
                        package_name = package["name"]
                except (tomllib.TOMLDecodeError, AttributeError) as exc:
                    self.error(f"cannot parse {member}/Cargo.toml: {exc}")
            if package_name is None:
                match = re.search(r'(?m)^\s*name\s*=\s*"([^"]+)"', package_text)
                package_name = match.group(1) if match else None
            if package_name is None:
                self.error(f"workspace member {member} has no package.name")
            else:
                cargo_names.append(package_name)

        expected = set(cargo_names)
        declared = set(declared_names)
        exact = config.get("exact") is True
        if exact and declared != expected:
            self.error(
                "bootstrap workspace scope must equal Cargo members: "
                f"missing={sorted(expected - declared)!r}, "
                f"extra={sorted(declared - expected)!r}"
            )
        elif not exact and not expected.issubset(declared):
            self.error(
                "bootstrap workspace scope omits Cargo members: "
                f"{sorted(expected - declared)!r}"
            )

        chain = scope.get("compiler_chain", [])
        chain_set = set(chain) if isinstance(chain, list) else set()
        for name in compiler_names:
            crate_path = f"bootstrap/crates/{name}"
            if crate_path not in chain_set:
                self.error(
                    f"compiler workspace member {name} is missing from scope.compiler_chain"
                )
        for name in auxiliary_names:
            crate_path = f"bootstrap/crates/{name}"
            if crate_path not in set(scope.get("auxiliary_bootstrap_consumers", [])):
                self.error(
                    f"auxiliary workspace member {name} must be listed in "
                    "scope.auxiliary_bootstrap_consumers"
                )
        self.info["workspace_scope"] = {
            "cargo_members": sorted(expected),
            "compiler_members": sorted(set(compiler_names)),
            "auxiliary_members": sorted(set(auxiliary_names)),
        }

    def check_generation(self, manifest: dict) -> None:
        generation = manifest.get("generation")
        if not isinstance(generation, dict):
            self.error("generation must be an object")
            return
        required = {
            "gen0": ("Gen1", "-O0"),
            "gen1": ("Gen2", "hosted"),
            "gen2": ("Gen3", "hosted"),
            "gen3": ("Gen4", "hosted"),
        }
        # Keep the generation graph executable, rather than treating the
        # producer/input fields as documentation-only labels.  In particular,
        # a typo that changes Gen0 to a release/hosted binary or skips the
        # declared source-manifest script would otherwise leave the checker
        # green while the chain script follows a different graph.
        expected_producers = {
            "gen0": "bootstrap/target/debug/xu",
            "gen1": "Gen0",
            "gen2": "Gen1",
            "gen3": "Gen2",
        }
        expected_input = "scripts/gen1_sources.sh"
        for stage, (output, mode_hint) in required.items():
            item = generation.get(stage)
            if not isinstance(item, dict):
                self.error(f"generation.{stage} must be an object")
                continue
            if item.get("producer") != expected_producers[stage]:
                self.error(
                    f"generation.{stage}.producer must be "
                    f"{expected_producers[stage]!r}"
                )
            if item.get("input") != expected_input:
                self.error(
                    f"generation.{stage}.input must be {expected_input!r}"
                )
            if item.get("output") != output:
                self.error(f"generation.{stage}.output must be {output}")
            mode = str(item.get("mode", ""))
            if mode_hint not in mode:
                self.error(f"generation.{stage}.mode must mention {mode_hint}")
        self.check_profiles(manifest, generation)
        warmup = generation.get("warmup")
        if not isinstance(warmup, dict):
            self.error("generation.warmup must be an object")
        else:
            if warmup.get("artifact") != "Gen2":
                self.error("generation.warmup.artifact must be Gen2")
            hops = warmup.get("max_transient_hops")
            if not isinstance(hops, int) or isinstance(hops, bool) or hops < 0:
                self.error("generation.warmup.max_transient_hops must be a non-negative integer")
        fixed = str(generation.get("fixed_point", ""))
        if not all(marker in fixed for marker in ("byte-identical", "Gen2", "Gen3", "Gen4", "skip")):
            self.error("generation.fixed_point must confirm Gen2/Gen3 byte identity or fall back to Gen3/Gen4")
        self.info["generation_fixed_point"] = fixed

    def check_frozen_primer_paths(self, manifest: dict) -> None:
        """Validate the machine-readable Gen0 artifact allowlist.

        Oracle harnesses may accept only a reproducible primer artifact.  The
        paths are lexical repository paths (not resolved symlink targets), so
        ``path()``/``regular_file()`` fail closed when a checkout replaces a
        component with a symlink to an external executable.  Build outputs
        are optional in a source checkout; when present they must be regular
        files.
        """

        invariants = manifest.get("invariants")
        if not isinstance(invariants, dict):
            self.error("invariants must be an object")
            return
        if invariants.get("oracle_requires_frozen_primer") is not True:
            self.error("oracle_requires_frozen_primer must be true")
        expected = [
            "bootstrap/target/debug/xu",
            "bootstrap/target/debug/xu.exe",
            "bootstrap/target/release/xu",
            "bootstrap/target/release/xu.exe",
        ]
        paths = invariants.get("frozen_primer_paths")
        if paths != expected:
            self.error(
                "frozen_primer_paths must list the canonical debug/release primer "
                f"paths exactly (got {paths!r})"
            )
            paths = expected if not isinstance(paths, list) else paths
        seen: set[str] = set()
        valid: list[str] = []
        for index, value in enumerate(paths):
            label = f"invariants.frozen_primer_paths[{index}]"
            if not isinstance(value, str):
                self.error(f"{label} must be a string")
                continue
            if value in seen:
                self.error(f"{label} is duplicated: {value}")
            seen.add(value)
            path = self.path(value, label)
            if path is None:
                continue
            valid.append(value)
            # A clean clone does not contain target artifacts yet.  If an
            # artifact exists, however, require a non-symlink regular file.
            if path.exists() and not self.regular_file(path, label):
                continue
        self.info["frozen_primer_paths"] = valid

    def check_oracle_path_guards(self, manifest: dict) -> None:
        """Ensure every lane entrypoint enforces the frozen-primer seam.

        The runtime checks live in small Python/shell consumers, so a schema
        check alone is insufficient: a later refactor could leave the
        manifest unchanged while dropping the path/symlink guard.  Keep the
        required marker set deliberately narrow and inspect executable source
        with comments removed.
        """

        invariants = manifest.get("invariants")
        if not isinstance(invariants, dict):
            self.error("invariants must be an object")
            return
        expected = [
            "scripts/cli_platform_test.sh",
            "scripts/check_crypto_constant_time_codegen.py",
            "scripts/deploy_xu_server.sh",
            "scripts/hardening_gate.sh",
            "scripts/language_eval.py",
            "scripts/platform_test.sh",
            "scripts/run_fixtures.sh",
            "scripts/scheduler_stress.py",
            "scripts/xu_doctor.py",
        ]
        paths = invariants.get("oracle_path_guard_scripts")
        if paths != expected:
            self.error(
                "oracle_path_guard_scripts must list every lane entrypoint "
                f"exactly (got {paths!r})"
            )
            paths = expected if not isinstance(paths, list) else paths

        python_markers = {
            "scripts/check_crypto_constant_time_codegen.py": (
                "FROZEN_PRIMER_PATHS",
                "is_frozen_primer",
            ),
            "scripts/scheduler_stress.py": ("FROZEN_PRIMER_PATHS", "_is_frozen_primer"),
            "scripts/xu_doctor.py": ("FROZEN_PRIMER_PATHS", "_is_frozen_primer"),
            "scripts/language_eval.py": ("FROZEN_PRIMER_PATHS", "is_frozen_primer"),
        }
        shell_markers = {
            "scripts/cli_platform_test.sh": ("is_frozen_primer_path", "has_symlink_component"),
            "scripts/deploy_xu_server.sh": ("is_frozen_primer_path", "has_symlink_component"),
            "scripts/platform_test.sh": ("is_frozen_primer_path", "has_symlink_component"),
            "scripts/run_fixtures.sh": ("is_frozen_primer_path", "has_symlink_component"),
            # hardening_gate selects scheduler's lane from a canonical path;
            # it accepts an explicitly hosted compiler but fail-closes any
            # non-canonical path below bootstrap.
            "scripts/hardening_gate.sh": (
                "is_primer_path",
                "is_frozen_primer_path",
                "SCHEDULER_LANE",
            ),
        }
        seen: list[str] = []
        if not isinstance(paths, list):
            paths = []
        for index, value in enumerate(paths):
            label = f"invariants.oracle_path_guard_scripts[{index}]"
            if not isinstance(value, str):
                self.error(f"{label} must be a string")
                continue
            path = self.path(value, label)
            if path is None or not self.regular_file(path, label):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.error(f"cannot read oracle path-guard script {value}: {exc}")
                continue
            active = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            markers = python_markers.get(value) or shell_markers.get(value)
            if markers is None:
                self.error(f"oracle path-guard script is not classified: {value}")
                continue
            for marker in markers:
                if marker not in active:
                    self.error(
                        f"oracle path-guard script {value} is missing active marker {marker}"
                    )
            seen.append(value)
        self.info["oracle_path_guard_scripts"] = sorted(seen)

        # Direct oracle harnesses that build/use a fixed bootstrap path must
        # delegate validation to xu_host_seed's strict mode.  This catches a
        # refactor that leaves the BOUNDARY_LANE=oracle banner intact while
        # accepting an external primer or a symlinked target.
        strict_expected = [
            "scripts/e2_qemu_hello.sh",
            "scripts/gen1_platform_test.sh",
            "scripts/gen1_test.sh",
            "scripts/programs_cross_check.sh",
            "scripts/safety_cross_target.sh",
            "scripts/safety_embedded.sh",
            "scripts/safety_escape_test.sh",
            "scripts/safety_test.sh",
            "scripts/test_runtime_data_alignment.sh",
            "scripts/test_runtime_lifetime_policy.sh",
            "scripts/test_string_temp_lifetime.sh",
            "scripts/test_vreg_matrix.sh",
            "scripts/test_vreg_selfhost.sh",
            "tests/platform_contract.sh",
        ]
        strict_paths = invariants.get("oracle_strict_resolver_scripts")
        if strict_paths != strict_expected:
            self.error(
                "oracle_strict_resolver_scripts must list every direct oracle "
                f"consumer exactly (got {strict_paths!r})"
            )
            strict_paths = (
                strict_expected if not isinstance(strict_paths, list) else strict_paths
            )
        strict_seen: list[str] = []
        if not isinstance(strict_paths, list):
            strict_paths = []
        for index, value in enumerate(strict_paths):
            if self.ci and isinstance(value, str) and value.startswith("tests/"):
                continue  # The complete Xu test corpus stays on the development machine.
            label = f"invariants.oracle_strict_resolver_scripts[{index}]"
            if not isinstance(value, str):
                self.error(f"{label} must be a string")
                continue
            path = self.path(value, label)
            if path is None or not self.regular_file(path, label):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.error(f"cannot read strict oracle consumer {value}: {exc}")
                continue
            active = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            for marker, description in (
                ("XU_REQUIRE_FROZEN_PRIMER=1", "strict frozen-primer resolver mode"),
                ("XU_ALLOW_ORACLE_SEED=1", "explicit oracle opt-in"),
                ("xu_host_seed.sh", "canonical seed resolver"),
            ):
                if marker not in active:
                    self.error(
                        f"strict oracle consumer {value} is missing {description} "
                        f"({marker})"
                    )
            strict_seen.append(value)
        self.info["oracle_strict_resolver_scripts"] = sorted(strict_seen)

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
        required_profiles = {
            "primer_oracle": ["-O0"],
            "hosted_product": [],
            "hosted_acceptance": ["-O1", "--ra=1"],
        }
        for name, expected_args in required_profiles.items():
            item = profiles.get(name)
            if not isinstance(item, dict):
                self.error(f"profiles.{name} must be an object")
                continue
            args = item.get("args")
            if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
                self.error(f"profiles.{name}.args must be a string list")
                continue
            if list(args) != expected_args:
                self.error(
                    f"profiles.{name}.args must be {expected_args!r}, got {args!r}"
                )
            lane = item.get("lane")
            if not isinstance(lane, str) or not lane:
                self.error(f"profiles.{name}.lane must be non-empty")

        gen0 = generation.get("gen0")
        if isinstance(gen0, dict):
            if gen0.get("profile") not in (None, "primer_oracle"):
                self.error("generation.gen0.profile must be primer_oracle")
            # Keep the old compact manifest valid while requiring the profile
            # to be explicit for new manifests.
            if gen0.get("profile") is None:
                self.warnings.append("generation.gen0.profile is implicit; add primer_oracle")
        for stage in ("gen1", "gen2", "gen3"):
            item = generation.get(stage)
            if not isinstance(item, dict):
                continue
            if item.get("profile") != "hosted_product":
                self.error(f"generation.{stage}.profile must be hosted_product")
            if item.get("acceptance_profile") != "hosted_acceptance":
                self.error(
                    f"generation.{stage}.acceptance_profile must be hosted_acceptance"
                )
        self.info["profiles"] = {
            name: profiles.get(name, {}).get("args", [])
            for name in required_profiles
            if isinstance(profiles.get(name), dict)
        }

    def check_mirrors(self, manifest: dict) -> None:
        mirrors = manifest.get("mirrors")
        if not isinstance(mirrors, list) or not mirrors:
            self.error("mirrors must be a non-empty list")
            return
        ids: set[str] = set()
        for index, mirror in enumerate(mirrors):
            if not isinstance(mirror, dict):
                self.error(f"mirrors[{index}] must be an object")
                continue
            mirror_id = mirror.get("id")
            if not isinstance(mirror_id, str) or not mirror_id:
                self.error(f"mirrors[{index}].id must be non-empty")
            elif mirror_id in ids:
                self.error(f"duplicate mirror id: {mirror_id}")
            else:
                ids.add(mirror_id)
            for side in ("product_paths", "primer_paths"):
                paths = mirror.get(side)
                if not isinstance(paths, list) or not paths:
                    self.error(f"mirrors[{index}].{side} must be a non-empty list")
                    continue
                for pindex, value in enumerate(paths):
                    if not isinstance(value, str):
                        self.error(f"mirrors[{index}].{side}[{pindex}] must be a string")
                        continue
                    path = self.path(value, f"mirrors[{index}].{side}[{pindex}]")
                    if path is not None and not path.exists():
                        self.error(f"mirrors[{index}].{side}[{pindex}]: path not found: {value}")

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
            for side in ("product_paths", "primer_paths"):
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
                            (".xu", ".rs"),
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
                for side in ("product_paths", "primer_paths"):
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
        # The resolver is allowed to mention the frozen primer in its
        # *guard*: an explicit XU_SEED pointing there may be used for oracle
        # recovery only.  What is forbidden is an unconditional primer/cargo
        # fallback.  Keep these checks semantic and narrow instead of banning
        # the word `bootstrap` everywhere (which would reject the guard and
        # its diagnostic).
        for marker, label in (
            ("XU_ALLOW_ORACLE_SEED", "explicit oracle opt-in"),
            ("XU_REQUIRE_FROZEN_PRIMER", "strict frozen-primer mode"),
            ("is_primer", "primer path classification"),
            ("is_frozen_primer", "canonical frozen-primer classification"),
            ("has_symlink_component", "primer symlink-component guard"),
            ("has_any_symlink_component", "external oracle alias guard"),
            ("select_explicit", "explicit seed path"),
            ("select_auto", "hosted auto-discovery"),
        ):
            if marker not in seed_active:
                self.error(f"xu_host_seed.sh is missing {label} guard ({marker})")
        if re.search(r"(?:^|[;&|]\s*)cargo(?:\s|$)", seed_active, re.IGNORECASE):
            self.error("xu_host_seed.sh must not invoke cargo")
        # The resolver may name the canonical paths inside its *classifier*;
        # what is forbidden is assigning one directly as an automatic seed or
        # fallback.  Keep the check assignment-oriented so the allowlist and
        # the no-fallback invariant can coexist.
        if re.search(
            r"(?im)^\s*(?:candidate|seed|compiler|xu)\s*=.*"
            r"bootstrap/target/(?:debug|release)/xu(?:\.exe)?",
            seed_active,
        ):
            self.error("xu_host_seed.sh must not hard-code a primer binary fallback")
        if not re.search(r"select_explicit\s+\"\$XU_SEED\"", seed_active):
            self.error("xu_host_seed.sh must require an explicit XU_SEED for oracle override")

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
        if "XU_ALLOW_ORACLE_SEED=0" not in makefile:
            self.error(
                "Makefile product lane must force XU_ALLOW_ORACLE_SEED=0 "
                "(oracle recovery is explicit only)"
            )
        for marker, label in (
            ("XU_SEED=\"$SEED_INPUT\"", "seed policy delegation"),
            ("XUPATH=\"\"", "clean XUPATH"),
            ("XU_CACHE=", "isolated XU_CACHE"),
            ("unset XUOS XUARCH", "fixed host target"),
            ("XU_ALLOW_ORACLE_INSTALL", "oracle install guard"),
            ("is_product_destination", "product destination classification"),
        ):
            if marker not in chain_active:
                self.error(f"build_hosted_chain.sh is missing {label} ({marker})")
        if re.search(r"bootstrap/target/(?:debug|release)/xu(?:\.exe)?", chain_active):
            self.error("build_hosted_chain.sh must not hard-code a primer seed")
        # An explicitly enabled oracle recovery chain may write a temporary
        # Gen4 for diagnosis, but it must stop before the product install
        # helpers.  Otherwise a primer run with DEST=/tmp/foo could still
        # mutate bin/platform or sibling tools and contaminate the next
        # product seed.
        oracle_guard = re.search(
            r'\[\s*"\$SEED_LANE"\s*=\s*"oracle"\s*\].*?XU_ALLOW_ORACLE_INSTALL',
            chain_active,
            re.DOTALL,
        )
        if oracle_guard is None:
            self.error(
                "build_hosted_chain.sh must guard oracle artifact installation "
                "with XU_ALLOW_ORACLE_INSTALL"
            )
        else:
            tools_pos = chain_active.find("./scripts/build_product_tools.sh")
            guard_pos = oracle_guard.start()
            if tools_pos >= 0 and guard_pos > tools_pos:
                self.error(
                    "build_hosted_chain.sh must evaluate the oracle install guard "
                    "before product_tools"
                )
        if "oracle artifact kept" not in chain_active:
            self.error(
                "build_hosted_chain.sh must report and isolate a non-installed "
                "oracle artifact"
            )
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

        selfhost_path = self.path(
            "scripts/test_vreg_selfhost.sh", "vreg acceptance profile script"
        )
        if selfhost_path is not None and self.regular_file(
            selfhost_path, "vreg acceptance profile script"
        ):
            try:
                selfhost = selfhost_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.error(f"cannot read vreg acceptance profile script: {exc}")
            else:
                selfhost_active = "\n".join(
                    line
                    for line in selfhost.splitlines()
                    if not line.lstrip().startswith("#")
                )
                if not re.search(r"hosted_args=\(\s*-O1\s+--ra=1\s*\)", selfhost_active):
                    self.error(
                        "test_vreg_selfhost.sh must pin the hosted_acceptance profile "
                        "(-O1 --ra=1)"
                    )

        self.info["profile_contract"] = {
            "product": product_args,
            "acceptance": acceptance_args,
            "chain_hops_pinned": len(hop_uses) == 3,
        }

    def _sync_ids(self) -> set[str]:
        """Read the synchronization ledger IDs without interpreting prose.

        Exception entries are deliberately tied to a ledger row.  Keeping the
        lookup here small and table-oriented means a paragraph mentioning an
        ID cannot accidentally authorize a new primer implementation.
        """

        if self.ci:
            return set()
        path = self.bootstrap_root / "SYNC_DIFF.md"
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.error(f"cannot read SYNC_DIFF.md for exception registration: {exc}")
            return set()
        return {
            match.group(1)
            for match in re.finditer(
                r"^\|\s*(SYNC-[A-Z][0-9]+)\s*\|", text, re.MULTILINE
            )
        }

    def _git_untracked_paths(self, relative_root: str) -> list[str]:
        """Return untracked paths below ``relative_root`` deterministically.

        The checker is also useful in source archives where Git is absent, so
        an unavailable Git command is a warning in ordinary mode and a hard
        failure only for ``--strict-freeze``.  We never invoke a shell here;
        path names are data, not commands.
        """

        in_bootstrap = relative_root.startswith("bootstrap/")
        git_root = self.bootstrap_root if in_bootstrap else self.root
        git_path = relative_root.removeprefix("bootstrap/") if in_bootstrap else relative_root
        try:
            proc = subprocess.run(
                [
                    "git",
                    "-C",
                    str(git_root),
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                    "--",
                    git_path,
                ],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            message = f"cannot inspect untracked bootstrap files: {exc}"
            if self.strict_freeze:
                self.error(message)
            else:
                self.warnings.append(message)
            return []
        if proc.returncode != 0:
            message = (
                "git ls-files failed while checking untracked bootstrap files: "
                + (proc.stderr.strip() or f"exit {proc.returncode}")
            )
            if self.strict_freeze:
                self.error(message)
            else:
                self.warnings.append(message)
            return []
        return sorted(
            {
                ("bootstrap/" if in_bootstrap else "") + line.strip()
                for line in proc.stdout.splitlines()
                if line.strip()
            },
            key=lambda value: value.encode("utf-8"),
        )

    def check_primer_exceptions(self, manifest: dict) -> None:
        """Enforce the explicit escape hatch for new Rust primer code.

        ``bootstrap/`` is frozen, but this checkout intentionally carries a
        few experimental Rust slices (the LLVM-style vreg tier and diagnostic
        helpers) plus auxiliary playground/build plumbing.  Without a
        machine-readable registration, an untracked Rust file can silently
        become part of a purported self-host result.  Normal checks report
        such files as warnings to keep local iteration usable; CI/release can
        pass ``--strict-freeze`` to fail closed.
        """

        sections = (
            ("experimental_primer_slices", "experimental"),
            ("auxiliary_bootstrap_slices", "auxiliary"),
        )
        sync_ids = self._sync_ids()
        registered: set[str] = set()
        entry_ids: set[str] = set()
        entry_count = 0

        for section_name, section_kind in sections:
            entries = manifest.get(section_name)
            if not isinstance(entries, list):
                self.error(f"{section_name} must be a list")
                continue
            for index, entry in enumerate(entries):
                entry_count += 1
                prefix = f"{section_name}[{index}]"
                if not isinstance(entry, dict):
                    self.error(f"{prefix} must be an object")
                    continue
                entry_id = entry.get("id")
                if not isinstance(entry_id, str) or not entry_id:
                    self.error(f"{prefix}.id must be a non-empty string")
                elif entry_id in entry_ids:
                    self.error(f"duplicate primer exception id: {entry_id}")
                else:
                    entry_ids.add(entry_id)

                paths = entry.get("paths")
                if not isinstance(paths, list) or not paths:
                    self.error(f"{prefix}.paths must be a non-empty list")
                    paths = []
                for pindex, value in enumerate(paths):
                    if not isinstance(value, str):
                        self.error(f"{prefix}.paths[{pindex}] must be a string")
                        continue
                    path = self.path(value, f"{prefix}.paths[{pindex}]")
                    if path is None or not self.regular_file(
                        path, f"{prefix}.paths[{pindex}]"
                    ):
                        continue
                    relative = self.relative(path).as_posix()
                    registered.add(relative)
                    # All exception paths must stay in the Rust workspace;
                    # product Xu files belong in mirror_paths instead.
                    if not relative.startswith("bootstrap/crates/"):
                        self.error(
                            f"{prefix}.paths[{pindex}] must be below bootstrap/crates: {value}"
                        )

                kind = entry.get("kind")
                lane = entry.get("lane")
                status = entry.get("status")
                sync_id = entry.get("sync_id")
                if not isinstance(kind, str) or not kind:
                    self.error(f"{prefix}.kind must be a non-empty string")
                if not isinstance(lane, str) or not lane:
                    self.error(f"{prefix}.lane must be a non-empty string")
                if status not in STATUS_VALUES:
                    self.error(
                        f"{prefix}.status must be one of {sorted(STATUS_VALUES)!r}"
                    )
                if not isinstance(sync_id, str) or not sync_id:
                    self.error(f"{prefix}.sync_id must be a non-empty string")
                elif not re.fullmatch(r"SYNC-[A-Z][0-9]+", sync_id):
                    self.error(f"{prefix}.sync_id must be a structured SYNC identifier")
                elif not self.ci and sync_id not in sync_ids:
                    self.error(f"{prefix}.sync_id is not present in SYNC_DIFF.md: {sync_id}")
                if entry.get("product_evidence") is not False:
                    self.error(f"{prefix}.product_evidence must be false")

                mirrors = entry.get("mirror_paths")
                if not isinstance(mirrors, list) or any(
                    not isinstance(item, str) for item in mirrors
                ):
                    self.error(f"{prefix}.mirror_paths must be a string list")
                    mirrors = []
                if section_kind == "experimental" and not mirrors:
                    self.error(
                        f"{prefix}.mirror_paths must name the Xu product counterpart"
                    )
                for mindex, value in enumerate(mirrors):
                    path = self.path(value, f"{prefix}.mirror_paths[{mindex}]")
                    if path is None or not path.exists():
                        self.error(
                            f"{prefix}.mirror_paths[{mindex}]: path not found: {value}"
                        )

                promotion = entry.get("promotion")
                if not isinstance(promotion, str) or not promotion.strip():
                    self.error(f"{prefix}.promotion must state a promotion condition")

        policy = manifest.get("untracked_policy")
        if not isinstance(policy, dict):
            self.error("untracked_policy must be an object")
            policy = {}
        suffixes = policy.get("implementation_suffixes")
        if not isinstance(suffixes, list) or any(
            not isinstance(item, str) or not item for item in suffixes
        ):
            self.error("untracked_policy.implementation_suffixes must be a string list")
            suffixes = []
        if policy.get("strict_requires_registration") is not True:
            self.error("untracked_policy.strict_requires_registration must be true")
        if policy.get("normal_mode") != "warn" or policy.get("strict_mode") != "fail":
            self.error("untracked_policy must use normal_mode=warn and strict_mode=fail")

        candidates: list[str] = []
        for value in self._git_untracked_paths("bootstrap/crates"):
            path = self.path(value, "untracked bootstrap implementation")
            if path is None:
                continue
            if path.name == "Cargo.toml" or any(
                path.name.endswith(suffix) for suffix in suffixes
            ):
                candidates.append(value)
        unregistered = sorted(set(candidates) - registered, key=lambda v: v.encode("utf-8"))
        for value in unregistered:
            message = (
                "untracked bootstrap implementation is not registered in "
                f"BOUNDARY.json: {value}"
            )
            if self.strict_freeze:
                self.error(message)
            else:
                self.warnings.append(message)

        self.info["primer_exceptions"] = {
            "entries": entry_count,
            "registered_paths": len(registered),
            "untracked_candidates": len(candidates),
            "unregistered_untracked": unregistered,
            "strict_freeze": self.strict_freeze,
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
            ("XU_ALLOW_ORACLE_SEED", "no recursive oracle override"),
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
                    ("XU_ALLOW_ORACLE_SEED=0", "oracle opt-in disabled"),
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
                ("XU_ALLOW_ORACLE_SEED=0", "oracle opt-in disabled"),
            ):
                if marker not in active:
                    self.error(f"product seed consumer {value} is missing {label_text} ({marker})")
            if re.search(r"\bcargo\s+(?:build|run|test)\b", active):
                self.error(f"product seed consumer {value} must not invoke cargo")
            primer_ref = bool(
                re.search(
                    r"bootstrap\s*/\s*target|ROOT\s*/\s*[\"']bootstrap[\"']|"
                    r"BOOT(?:STRAP)?[_-]XU|ROOT_DIR\s*/\s*[\"']bootstrap[\"']",
                    active,
                    re.IGNORECASE,
                )
            )
            if primer_ref:
                explicit_oracle = bool(
                    re.search(
                        r"--oracle|lane\s*(?:==|in|=)\s*[\"']oracle[\"']|"
                        r"XU_ALLOW_ORACLE_SEED\s*[:=]",
                        active,
                        re.IGNORECASE,
                    )
                )
                rejection_guard = bool(
                    re.search(
                        r"is_primer|primer_path|refusing .*primer|primer.*oracle-only|"
                        r"not.*product.*fallback",
                        active,
                        re.IGNORECASE,
                    )
                )
                if not explicit_oracle and not rejection_guard:
                    self.error(
                        f"product seed consumer {value} references bootstrap without "
                        "an explicit oracle branch or rejection guard"
                    )
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

        # Keep the recovery/oracle side explicit as well.  We validate the
        # declared paths and disjointness here; each script owns its detailed
        # diagnostic policy, but none may silently become a product consumer.
        oracle_cfg = manifest.get("oracle_consumers")
        oracle_ids: set[str] = set()
        if not isinstance(oracle_cfg, dict):
            self.error("oracle_consumers must be an object")
        else:
            oracle_paths = oracle_cfg.get("paths")
            if not isinstance(oracle_paths, list) or not oracle_paths:
                self.error("oracle_consumers.paths must be a non-empty list")
                oracle_paths = []
            oracle_lane_annotations: list[str] = []
            for index, value in enumerate(oracle_paths):
                if not isinstance(value, str):
                    self.error(f"oracle_consumers.paths[{index}] must be a string")
                    continue
                if value in oracle_ids:
                    self.error(f"oracle_consumers.paths contains duplicate path: {value}")
                oracle_ids.add(value)
                path = self.path(value, f"oracle_consumers.paths[{index}]")
                if path is not None and not self.regular_file(
                    path, f"oracle_consumers.paths[{index}]"
                ):
                    continue
                if path is None:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    self.error(f"cannot read oracle consumer {value}: {exc}")
                    continue
                active = "\n".join(
                    line
                    for line in text.splitlines()
                    if not line.lstrip().startswith("#")
                )
                # A filename/comment is not a sufficient lane declaration:
                # require an executable assignment so a refactor cannot make
                # the frozen primer an implicit product dependency.
                if not re.search(
                    r"(?:^|\n)[ \t]*BOUNDARY_LANE[ \t]*=[ \t]*(?:['\"]oracle['\"]|oracle)[ \t]*(?=\n|$|#)",
                    active,
                    re.IGNORECASE,
                ):
                    self.error(
                        f"oracle consumer {value} is missing active "
                        "BOUNDARY_LANE=oracle marker"
                    )
                else:
                    oracle_lane_annotations.append(value)
            overlap = sorted(oracle_ids & (consumer_ids | orchestrator_ids))
            if overlap:
                self.error(
                    "oracle_consumers must be disjoint from product consumers/orchestrators: "
                    + ", ".join(overlap)
                )
            if oracle_cfg.get("explicit_only") is not True:
                self.error("oracle_consumers.explicit_only must be true")
        self.info["oracle_consumers"] = sorted(oracle_ids)
        self.info["oracle_lane_annotations"] = sorted(oracle_lane_annotations)

    def check_product_bootstrap_reference(self, value: str, active_text: str) -> None:
        """Require every product-side primer mention to be guarded.

        Product wrappers may need to *recognise* a primer in order to reject
        it, and a few mixed tools expose an explicit oracle diagnostic mode.
        What is forbidden is an unguarded ``bootstrap/target`` candidate that
        can become the product compiler by accident.  This check deliberately
        accepts either a rejection guard (``is_primer``/``primer_path``) or an
        explicit oracle branch; the resolver and wrapper checks above still
        enforce the actual product path.
        """

        primer_reference = bool(
            re.search(
                r"bootstrap\s*/\s*target|ROOT\s*/\s*[\"']bootstrap[\"']|"
                r"BOOT(?:STRAP)?[_-]XU|ROOT_DIR\s*/\s*[\"']bootstrap[\"']",
                active_text,
                re.IGNORECASE,
            )
        )
        if not primer_reference:
            return
        explicit_oracle = bool(
            re.search(
                r"--oracle|lane\s*(?:==|in|=)\s*[\"']oracle[\"']|"
                r"XU_ALLOW_ORACLE_SEED\s*[:=]",
                active_text,
                re.IGNORECASE,
            )
        )
        rejection_guard = bool(
            re.search(
                r"is_primer|primer_path|refusing .*primer|primer.*oracle-only|"
                r"not.*product.*fallback",
                active_text,
                re.IGNORECASE,
            )
        )
        if not explicit_oracle and not rejection_guard:
            self.error(
                f"product consumer {value} references bootstrap without an explicit "
                "oracle branch or primer rejection guard"
            )

    def check_lane_consumers(self, manifest: dict) -> None:
        """Validate explicitly labelled diagnostic and dual-lane harnesses.

        These scripts are intentionally outside the direct product-consumer
        seam: some run the frozen Rust primer, while others compare primer and
        hosted outputs. Keeping them in separate manifest sections prevents a
        benchmark/contract probe from being mistaken for a product build, and
        requires an active (non-comment) lane marker in each script.
        """

        sections = (
            ("diagnostic_consumers", "oracle"),
            ("dual_consumers", "dual"),
        )
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
        oracle_cfg = manifest.get("oracle_consumers")
        oracle_ids = {
            value
            for value in (
                oracle_cfg.get("paths", []) if isinstance(oracle_cfg, dict) else []
            )
            if isinstance(value, str)
        }
        claimed: set[str] = set()
        report: dict[str, list[str]] = {}

        for section, expected_lane in sections:
            cfg = manifest.get(section)
            if not isinstance(cfg, dict):
                self.error(f"{section} must be an object")
                report[section] = []
                continue
            if cfg.get("lane") != expected_lane:
                self.error(
                    f"{section}.lane must be {expected_lane!r} "
                    f"(got {cfg.get('lane')!r})"
                )
            if cfg.get("explicit_only") is not True:
                self.error(f"{section}.explicit_only must be true")
            paths = cfg.get("paths")
            if not isinstance(paths, list) or not paths:
                self.error(f"{section}.paths must be a non-empty list")
                paths = []
            ids: set[str] = set()
            for index, value in enumerate(paths):
                label = f"{section}.paths[{index}]"
                if not isinstance(value, str):
                    self.error(f"{label} must be a string")
                    continue
                if value in ids:
                    self.error(f"{section}.paths contains duplicate path: {value}")
                ids.add(value)
                if value in claimed:
                    self.error(f"lane consumer path appears in multiple sections: {value}")
                claimed.add(value)
                if value in product_ids or value in orchestrator_ids or value in oracle_ids:
                    self.error(
                        f"{section} must be disjoint from product/oracle consumers: {value}"
                    )
                path = self.path(value, label)
                if self.ci and value.startswith("tests/"):
                    # Keep lane/disjointness checks above; local test bodies
                    # are intentionally absent from a public checkout.
                    if path is not None:
                        self.info.setdefault("local_test_consumers_excluded", []).append(value)
                    continue
                if path is None or not self.regular_file(path, label):
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    self.error(f"cannot read {section} consumer {value}: {exc}")
                    continue
                active = "\n".join(
                    line
                    for line in text.splitlines()
                    if not line.lstrip().startswith("#")
                )
                # Require an executable marker, not only a documentation
                # comment, so a future refactor cannot silently change lanes.
                marker = re.search(
                    rf"\bLANE\s*=\s*['\"]?{re.escape(expected_lane)}\b|"
                    rf"\blane\s*=\s*['\"]?{re.escape(expected_lane)}\b",
                    active,
                    re.IGNORECASE,
                )
                if marker is None:
                    self.error(
                        f"{section} consumer {value} is missing active lane={expected_lane} marker"
                    )
            report[section] = sorted(ids)

        self.info["diagnostic_consumers"] = report.get("diagnostic_consumers", [])
        self.info["dual_consumers"] = report.get("dual_consumers", [])
        self.info["lane_consumers"] = report

        # Dual harnesses are allowed to call the frozen primer directly for
        # the oracle side, but every path that also compiles the hosted side
        # must cross the same product resolver/wrapper seam as a normal
        # product consumer.  Keep this subset explicit: mixed report drivers
        # (for example language_eval.py) delegate to these paths and do not
        # need to duplicate the wrapper implementation.
        dual_cfg = manifest.get("dual_consumers")
        compile_paths = (
            dual_cfg.get("product_compile_paths", [])
            if isinstance(dual_cfg, dict)
            else []
        )
        if not isinstance(compile_paths, list) or not compile_paths:
            self.error("dual_consumers.product_compile_paths must be a non-empty list")
            compile_paths = []
        dual_ids = set(report.get("dual_consumers", []))
        compile_ids: set[str] = set()
        for index, value in enumerate(compile_paths):
            label = f"dual_consumers.product_compile_paths[{index}]"
            if not isinstance(value, str):
                self.error(f"{label} must be a string")
                continue
            if value in compile_ids:
                self.error(f"dual_consumers.product_compile_paths contains duplicate path: {value}")
            compile_ids.add(value)
            if value not in dual_ids:
                self.error(f"dual product compile path is not a dual consumer: {value}")
                continue
            path = self.path(value, label)
            if path is None or not self.regular_file(path, label):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.error(f"cannot read dual product compile consumer {value}: {exc}")
                continue
            active = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            for marker, description in (
                ("HOST_SEED_RESOLVER", "hosted seed resolver"),
                ("PRODUCT_COMPILER_RUNNER", "hermetic product compiler runner"),
                ("run_product_compiler.sh", "product wrapper invocation"),
            ):
                if marker not in active:
                    self.error(
                        f"dual product compile consumer {value} is missing "
                        f"{description} ({marker})"
                    )
            self.check_product_bootstrap_reference(value, active)
        self.info["dual_product_compile_paths"] = sorted(compile_ids)

    def check_product_probes(self, manifest: dict) -> None:
        """Check lane-aware product diagnostics that do not compile sources.

        A few compatibility tools (currently ``xu_doctor.py``) inspect the
        compiler/toolchain without going through the compiler invocation
        wrapper.  They still sit on the product-facing boundary: the default
        probe must resolve a hosted seed, while primer inspection is an
        explicit oracle mode.  Keeping this category separate prevents the
        direct-consumer rule from requiring a pointless compile wrapper while
        still catching the old ``bootstrap/target`` silent fallback.
        """

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
        oracle_cfg = manifest.get("oracle_consumers")
        oracle_ids = {
            value
            for value in (
                oracle_cfg.get("paths", []) if isinstance(oracle_cfg, dict) else []
            )
            if isinstance(value, str)
        }
        lane_cfg = {
            value
            for section in ("diagnostic_consumers", "dual_consumers")
            for value in (
                manifest.get(section, {}).get("paths", [])
                if isinstance(manifest.get(section), dict)
                else []
            )
            if isinstance(value, str)
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
            if value in product_ids | orchestrator_ids | oracle_ids | lane_cfg:
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
                ("XU_ALLOW_ORACLE_SEED", "explicit oracle switch"),
                ("--oracle", "oracle command-line mode"),
                ("lane", "lane selection"),
            ):
                if marker not in active:
                    self.error(f"product probe {value} is missing {description} ({marker})")
            if re.search(r"\bcargo\s+(?:build|run|test)\b", active):
                self.error(f"product probe {value} must not invoke cargo")
            # A probe may mention bootstrap only inside its explicit oracle
            # fallback.  Require both a lane branch and the resolver guard so
            # a future unconditional candidate list cannot pass by accident.
            if "bootstrap/target" in active and not re.search(
                r"lane\s*==\s*[\"']oracle[\"']|lane\s*in\s*\{[^}]*oracle",
                active,
            ):
                self.error(
                    f"product probe {value} mentions bootstrap without an explicit oracle branch"
                )
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
            "seed-resolver": ("XU_ALLOW_ORACLE_SEED", "select_auto", "select_explicit"),
            "generation-orchestrator": (
                "HOSTED_PROFILE",
                "XU_ALLOW_ORACLE_INSTALL",
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
            "top-level-entrypoints": ("product-selfhost", "oracle", "build_hosted_chain.sh"),
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
        """Prevent CI primer probes from masquerading as product builds."""

        workflow_paths = (
            (".github/workflows/ci.yml", "ci workflow"),
            (".github/workflows/windows.yml", "windows workflow"),
            (".github/workflows/oracle.yml", "oracle workflow"),
        )
        checked: list[str] = []
        for value, label in workflow_paths:
            path = self.path(value, label)
            if path is None or not self.regular_file(path, label):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.error(f"cannot read {label}: {exc}")
                continue
            active = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            # The fast CI job intentionally uses the Rust primer for a cheap
            # server smoke before a hosted seed exists.  It must say --oracle
            # on the same command; otherwise a future product-only parser
            # change could silently turn this into an ambiguous invocation.
            for line_no, line in enumerate(active.splitlines(), 1):
                if "bootstrap/target" in line and "deploy_xu_server.sh" in line:
                    if "--oracle" not in line:
                        self.error(
                            f"{value}:{line_no}: bootstrap deploy must be explicit --oracle"
                        )
                if "bootstrap/target" in line and "run_fixtures.sh" in line:
                    if "--label=oracle" not in line:
                        self.error(
                            f"{value}:{line_no}: bootstrap fixture run must be labelled oracle"
                        )
            if value.endswith("windows.yml"):
                # Windows currently exercises the primer directly.  Keep the
                # job identity explicit until a hosted Windows seed is wired.
                if not re.search(r"name:\s*windows[^\n]*oracle", text, re.IGNORECASE):
                    self.error(
                        "windows workflow using bootstrap must identify itself as oracle"
                    )
            if value.endswith("oracle.yml"):
                # The scheduled/manual workflow is intentionally a primer
                # oracle lane.  Require both the workflow identity and the
                # explicit oracle target so a future copy/paste cannot turn
                # it into an unlabeled product build.
                if not re.search(r"(?im)^\s*name:\s*oracle\b", text):
                    self.error("oracle workflow must identify itself as oracle")
                if not re.search(r"\bmake\s+oracle\b|(?:\./)?scripts/oracle_platform_chain\.sh(?=\s|$)", active):
                    self.error("oracle workflow must invoke `make oracle` or `scripts/oracle_platform_chain.sh`")
                if not re.search(r"XU_CI_LANE\s*=\s*oracle|lane\s*[:=]\s*oracle", active, re.IGNORECASE):
                    self.error("oracle workflow must carry an active lane=oracle marker")
                if re.search(r"\bmake\s+(?:xu|product-selfhost|selfhost)\b", active):
                    self.error("oracle workflow must not invoke a product self-host target")
                if "bootstrap" not in text.lower() and "primer" not in text.lower():
                    self.error("oracle workflow must state its bootstrap/primer role")
            checked.append(value)
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

    def check_watermark_allowlist(self, manifest: dict) -> None:
        invariants = manifest.get("invariants", {})
        allowlist = invariants.get("watermark_source_allowlist", [])
        if not isinstance(allowlist, list) or not allowlist:
            self.error("watermark_source_allowlist must be a non-empty list")
            return
        allowed: set[str] = set()
        for item in allowlist:
            if not isinstance(item, str):
                self.error("watermark_source_allowlist entries must be strings")
                continue
            path = self.path(item, "watermark_source_allowlist")
            if path is None:
                continue
            allowed.add(self.relative(path).as_posix())
        literal = "xu830103"
        scan_roots = [self.bootstrap_root / "crates"]
        scan_paths: set[Path] = set()
        for root in scan_roots:
            # Walk without following symlinks so a primer watermark cannot be
            # smuggled through an aliased crate source tree.
            scan_paths.update(self.source_files_under(root, (".rs",), "watermark scan"))
        for allowed_path in allowlist:
            path = self.path(str(allowed_path), "watermark_source_allowlist")
            if path is not None:
                scan_paths.add(path)
        for path in sorted(scan_paths):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.error(f"cannot read bootstrap source {path}: {exc}")
                continue
            if literal in text and self.relative(path).as_posix() not in allowed:
                self.error(
                    f"watermark literal {literal} is outside the allowlist: "
                    f"{self.relative(path)}"
                )

    def check_sync_diff_schema(self) -> None:
        if self.ci:
            self.info["local_ledger"] = "excluded from CI; source and exception checks remain enforced"
            return
        path = self.bootstrap_root / "SYNC_DIFF.md"
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.error(f"cannot read SYNC_DIFF.md: {exc}")
            return
        ids: set[str] = set()
        counts = {status: 0 for status in STATUS_VALUES}
        for line_no, line in enumerate(text.splitlines(), 1):
            if not re.match(r"^\|\s*SYNC-[A-Z][0-9]+\s*\|", line):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 4:
                self.error(f"SYNC_DIFF.md:{line_no}: malformed ledger row")
                continue
            entry_id = cells[0]
            # Section tables have either five or six columns.  Locate the
            # status cell by value instead of relying on one column index.
            status_cells = [cell.strip("`* ") for cell in cells if cell.strip("`* ") in STATUS_VALUES]
            status = status_cells[0] if len(status_cells) == 1 else ""
            if entry_id in ids:
                self.error(f"SYNC_DIFF.md:{line_no}: duplicate id {entry_id}")
            ids.add(entry_id)
            if status not in STATUS_VALUES:
                self.error(f"SYNC_DIFF.md:{line_no}: invalid status {status!r}")
            else:
                counts[status] += 1
        if not ids:
            self.error("SYNC_DIFF.md contains no SYNC-* ledger rows")
        self.info["sync_diff"] = {"entries": len(ids), "statuses": counts}

    def run(self, manifest: dict) -> None:
        self.check_required_paths(manifest)
        self.check_roles(manifest)
        self.check_generation(manifest)
        self.check_frozen_primer_paths(manifest)
        self.check_oracle_path_guards(manifest)
        self.check_primer_exceptions(manifest)
        self.check_mirrors(manifest)
        self.check_runtime_abi(manifest)
        self.check_runtime_contract_registry(manifest)
        self.check_product_source_purity(manifest)
        self.check_seed_and_chain_scripts()
        self.check_profile_scripts(manifest)
        self.check_product_compiler_wrapper(manifest)
        self.check_product_probes(manifest)
        self.check_boundary_infrastructure(manifest)
        self.check_lane_consumers(manifest)
        self.check_ci_lane_annotations()
        self.check_source_manifest(manifest)
        self.check_watermark_allowlist(manifest)
        self.check_sync_diff_schema()


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
        help="boundary manifest (default: bootstrap/BOUNDARY.json)",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    parser.add_argument("--ci", action="store_true", default=os.environ.get("XU_BOUNDARY_CI") == "1",
                        help="check published sources without local docs or SYNC_DIFF.md")
    parser.add_argument(
        "--strict-freeze",
        action="store_true",
        help="fail when an untracked bootstrap implementation is not registered",
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
        and "oracle_consumers" in check.info,
        "product_seed_consumer_seam": "product_seed_consumers" in check.info,
        "lane_consumer_seam": "diagnostic_consumers" in check.info
        and "dual_consumers" in check.info,
        "product_probe_seam": "product_probes" in check.info,
        "ci_lane_annotations": "ci_lane_annotations" in check.info,
        "primer_exception_registration": "primer_exceptions" in check.info,
        "sync_diff": "sync_diff" in check.info,
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
            print("bootstrap/Xu boundary: FAIL")
        else:
            print("bootstrap/Xu boundary: PASS")
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
        if "primer_exceptions" in report:
            exceptions = report["primer_exceptions"]
            assert isinstance(exceptions, dict)
            print(
                "  primer exception paths: "
                f"{exceptions['registered_paths']} "
                f"(untracked candidates={exceptions['untracked_candidates']})"
            )
        sync = report.get("sync_diff")
        if isinstance(sync, dict):
            print(f"  SYNC_DIFF entries: {sync['entries']}")
            print(f"  SYNC_DIFF status counts: {sync['statuses']}")
    for warning in check.warnings:
        print(f"boundary: warning: {warning}", file=sys.stderr)
    for error in check.errors:
        print(f"boundary: error: {error}", file=sys.stderr)
    return 1 if check.errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
