"""Focused regression tests for the bootstrap/Xu source-of-truth seam.

This file intentionally uses ``unittest`` only.  The repository's broad
pytest discovery can walk generated Wine/Tk trees; these tests remain runnable
directly with ``python3 -m unittest`` or as a narrow pytest target.
"""

from __future__ import annotations

import importlib.util
import json
import os
import copy
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from companion_repos import project_root
BOOTSTRAP_ROOT = project_root("bootstrap")
CHECKER_PATH = ROOT / "scripts" / "check_bootstrap_xu_boundary.py"
SPEC = importlib.util.spec_from_file_location("xu_boundary_checker", CHECKER_PATH)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class BootstrapBoundaryContractTests(unittest.TestCase):
    def test_ci_scope_excludes_only_local_materials(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            manifest = {"required_paths": ["docs/local.md", "bootstrap/SYNC_DIFF.md", "src/needed.xu"]}
            check = checker.BoundaryCheck(root, root / "manifest", ci=True)
            check.check_required_paths(manifest)
            check.check_sync_diff_schema()
            self.assertEqual(len(check.errors), 1)
            self.assertIn("src/needed.xu", check.errors[0])
            local = checker.BoundaryCheck(root, root / "manifest")
            local.check_required_paths(manifest)
            local.check_sync_diff_schema()
            self.assertGreaterEqual(len(local.errors), 3)

    def test_independent_bootstrap_paths_keep_repository_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder).resolve()
            core = parent / "xu"
            bootstrap = parent / "primer checkout"
            core.mkdir()
            (bootstrap / "crates").mkdir(parents=True)
            source = bootstrap / "crates" / "source.rs"
            source.write_text("frozen source")
            with unittest.mock.patch.dict(os.environ, XU_BOOTSTRAP_ROOT=str(bootstrap)):
                check = checker.BoundaryCheck(core, bootstrap / "BOUNDARY.json")
                self.assertEqual(check.path("bootstrap/crates/source.rs", "test"), source)
                self.assertEqual(check.relative(source).as_posix(), "bootstrap/crates/source.rs")
                self.assertTrue(check.regular_file(source, "test"))
                (bootstrap / "crates/alias.rs").symlink_to(core / "outside.rs")
                self.assertIsNone(check.path("bootstrap/crates/alias.rs", "test"))
                self.assertIsNone(check.path("bootstrap/../xu/outside.rs", "test"))

    def test_freeze_reads_the_independent_bootstrap_git_index(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder).resolve()
            core, bootstrap = parent / "xu", parent / "bootstrap"
            core.mkdir()
            (bootstrap / "crates").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(bootstrap)], check=True)
            (bootstrap / "crates/frozen.rs").write_text("registered source")
            subprocess.run(["git", "-C", str(bootstrap), "add", "--", "crates/frozen.rs"], check=True)
            (bootstrap / "crates/new.rs").write_text("unregistered source")
            with unittest.mock.patch.dict(os.environ, XU_BOOTSTRAP_ROOT=str(bootstrap)):
                check = checker.BoundaryCheck(core, bootstrap / "BOUNDARY.json", strict_freeze=True)
                self.assertEqual(check._git_untracked_paths("bootstrap/crates"), ["bootstrap/crates/new.rs"])

    def test_independent_primer_requires_explicit_oracle_lane(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder).resolve()
            core, bootstrap = parent / "xu", parent / "primer checkout"
            (core / "scripts").mkdir(parents=True)
            resolver = core / "scripts/xu_host_seed.sh"
            shutil.copy2(ROOT / "scripts/xu_host_seed.sh", resolver)
            primer = bootstrap / "target/debug/xu"
            primer.parent.mkdir(parents=True)
            primer.write_text("#!/bin/sh\nexit 0\n")
            primer.chmod(0o755)
            env = dict(os.environ, XU_BOOTSTRAP_ROOT=str(bootstrap), XU_SEED=str(primer),
                       XU_ALLOW_ORACLE_SEED="0", XU_REQUIRE_FROZEN_PRIMER="0")
            product = subprocess.run([str(resolver)], env=env, capture_output=True, text=True)
            self.assertNotEqual(product.returncode, 0)
            self.assertIn("primer as product seed", product.stderr)
            env.update(XU_ALLOW_ORACLE_SEED="1", XU_REQUIRE_FROZEN_PRIMER="1")
            oracle = subprocess.run([str(resolver)], env=env, capture_output=True, text=True)
            self.assertEqual(oracle.returncode, 0, oracle.stderr)
            self.assertEqual(oracle.stdout.strip(), str(primer))

    @staticmethod
    def _load_script_module(name: str, relative: str):
        """Load one lane resolver without relying on package installation."""

        path = ROOT / relative
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # dataclasses (used by the benchmark helpers) resolve annotations via
        # sys.modules while the module is being executed.
        import sys

        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    def test_manifest_closure_is_distinct_from_seed(self) -> None:
        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        check = checker.BoundaryCheck(ROOT, BOOTSTRAP_ROOT / "BOUNDARY.json")
        check.run(manifest)
        self.assertFalse(check.errors, "boundary checker errors: " + repr(check.errors))
        report = check.info["source_manifest"]
        self.assertEqual(report["seed_files"], sum(len(list((ROOT / d).glob("*.xu"))) for d in manifest["source_manifest"]["seed_domains"]))
        self.assertIn("strconv", report["stdlib_modules"])
        self.assertEqual(report["closure_files"], report["seed_files"] + report["stdlib_closure_files"])
        self.assertNotEqual(report["seed_sha256"], report["closure_sha256"])
        self.assertTrue(report["complete"])

    def test_generation_has_explicit_warmup_and_confirmation(self) -> None:
        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        generation = manifest["generation"]
        self.assertEqual(generation["gen3"]["output"], "Gen4")
        self.assertEqual(generation["warmup"]["artifact"], "Gen2")
        self.assertEqual(generation["warmup"]["max_transient_hops"], 1)
        self.assertIn("Gen3", generation["fixed_point"])
        self.assertIn("Gen4", generation["fixed_point"])
        self.assertIn("Gen2", generation["fixed_point"])
        chain = (ROOT / "scripts" / "build_hosted_chain.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('"$G3" build "${HOSTED_ARGS[@]}"', chain)
        self.assertIn('cmp "$G3" "$G4"', chain)
        self.assertIn('if cmp -s "$G2" "$G3"; then', chain)
        self.assertIn('bash ./scripts/install_product_executable.sh "$CONFIRMED" "$DEST"', chain)
        self.assertTrue(manifest["invariants"]["oracle_requires_frozen_primer"])
        self.assertEqual(
            manifest["invariants"]["frozen_primer_paths"],
            [
                "bootstrap/target/debug/xu",
                "bootstrap/target/debug/xu.exe",
                "bootstrap/target/release/xu",
                "bootstrap/target/release/xu.exe",
            ],
        )

    def test_chain_rejects_an_installer_without_atomic_commit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts").mkdir()
            shutil.copy2(ROOT / "Makefile", root / "Makefile")
            for name in ("build_hosted_chain.sh", "xu_host_seed.sh", "install_product_executable.sh"):
                shutil.copy2(ROOT / "scripts" / name, root / "scripts" / name)
            installer = root / "scripts/install_product_executable.sh"
            installer.write_text(installer.read_text().replace('mv -f "$install_staged" "$install_destination"',
                                                               'cp "$install_staged" "$install_destination"'))
            check = checker.BoundaryCheck(root, root / "bootstrap/BOUNDARY.json")
            check.check_seed_and_chain_scripts()
            self.assertTrue(any("atomic installer" in error for error in check.errors), check.errors)

    def test_generation_graph_rejects_producer_or_input_drift(self) -> None:
        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        mutated = copy.deepcopy(manifest)
        mutated["generation"]["gen2"]["producer"] = "Gen0"
        mutated["generation"]["gen3"]["input"] = "scripts/other_sources.sh"
        check = checker.BoundaryCheck(ROOT, BOOTSTRAP_ROOT / "BOUNDARY.json")
        check.check_generation(mutated)
        self.assertTrue(any("generation.gen2.producer" in e for e in check.errors))
        self.assertTrue(any("generation.gen3.input" in e for e in check.errors))

    def test_manifest_path_rejects_symlink_even_in_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real").write_text("ok", encoding="utf-8")
            (root / "alias").symlink_to(root / "real")
            check = checker.BoundaryCheck(root, root / "manifest")
            self.assertIsNone(check.path("alias", "test"))
            self.assertTrue(any("symlink" in error for error in check.errors))

    def test_frozen_primer_allowlist_rejects_symlink_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "outside-xu"
            target.write_text("primer", encoding="utf-8")
            debug_dir = root / "bootstrap" / "target" / "debug"
            debug_dir.mkdir(parents=True)
            (debug_dir / "xu").symlink_to(target)
            (root / "bootstrap" / "target" / "release").mkdir(parents=True)
            check = checker.BoundaryCheck(root, root / "manifest")
            check.check_frozen_primer_paths(
                {
                    "invariants": {
                        "oracle_requires_frozen_primer": True,
                        "frozen_primer_paths": [
                            "bootstrap/target/debug/xu",
                            "bootstrap/target/debug/xu.exe",
                            "bootstrap/target/release/xu",
                            "bootstrap/target/release/xu.exe",
                        ],
                    }
                }
            )
            self.assertTrue(any("symlink" in error for error in check.errors))

    def test_seed_resolver_rejects_symlinked_primer_target(self) -> None:
        """The shell resolver must not bless an external symlink target."""

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "scripts").mkdir(parents=True)
            (repo / "bootstrap" / "target" / "debug").mkdir(parents=True)
            (repo / "bootstrap" / "target" / "release").mkdir(parents=True)
            shutil.copy2(
                ROOT / "scripts" / "xu_host_seed.sh",
                repo / "scripts" / "xu_host_seed.sh",
            )
            (repo / "bootstrap" / "target" / "debug" / "xu").symlink_to(
                "/bin/echo"
            )
            proc = subprocess.run(
                [str(repo / "scripts" / "xu_host_seed.sh")],
                cwd=repo,
                env={
                    **os.environ,
                    "XU_ALLOW_ORACLE_SEED": "1",
                    "XU_SEED": "bootstrap/target/debug/xu",
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("non-canonical bootstrap executable", proc.stderr)

            # An alias outside this checkout that points at the real frozen
            # artifact is still rejected: oracle evidence must name this
            # repository's lexical allowlist entry, not an arbitrary symlink.
            alias = repo / "alias-xu"
            alias.symlink_to(BOOTSTRAP_ROOT / "target" / "debug" / "xu")
            alias_proc = subprocess.run(
                [str(repo / "scripts" / "xu_host_seed.sh")],
                cwd=repo,
                env={
                    **os.environ,
                    "XU_ALLOW_ORACLE_SEED": "1",
                    "XU_SEED": str(alias),
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(alias_proc.returncode, 0)
            self.assertIn("non-canonical bootstrap executable", alias_proc.stderr)

            # Direct oracle consumers use the resolver's strict mode too;
            # an arbitrary executable must not become oracle evidence merely
            # because XU_ALLOW_ORACLE_SEED is enabled.
            external_proc = subprocess.run(
                [str(ROOT / "scripts" / "xu_host_seed.sh")],
                cwd=ROOT,
                env={
                    **os.environ,
                    "XU_ALLOW_ORACLE_SEED": "1",
                    "XU_REQUIRE_FROZEN_PRIMER": "1",
                    "XU_SEED": "/bin/echo",
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(external_proc.returncode, 0)
            self.assertIn("non-canonical bootstrap executable", external_proc.stderr)

    def test_seed_resolver_rejects_executable_directory(self) -> None:
        """The frozen primer must be a regular executable file, not a dir."""

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "scripts").mkdir(parents=True)
            debug = repo / "bootstrap" / "target" / "debug"
            (repo / "bootstrap" / "target" / "release").mkdir(parents=True)
            debug.mkdir(parents=True)
            shutil.copy2(
                ROOT / "scripts" / "xu_host_seed.sh",
                repo / "scripts" / "xu_host_seed.sh",
            )
            # Directories may satisfy ``test -x``; the resolver must still
            # reject this impostor before any oracle consumer executes it.
            fake = debug / "xu"
            fake.mkdir()
            fake.chmod(0o755)
            proc = subprocess.run(
                [str(repo / "scripts" / "xu_host_seed.sh")],
                cwd=repo,
                env={
                    **os.environ,
                    "XU_ALLOW_ORACLE_SEED": "1",
                    "XU_REQUIRE_FROZEN_PRIMER": "1",
                    "XU_SEED": "bootstrap/target/debug/xu",
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("non-canonical bootstrap executable", proc.stderr)

    def test_dotted_module_ids_follow_driver_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "foo").mkdir(parents=True)
            (root / "src" / "foo" / "bar.xu").write_text(
                "module: foo/bar\n", encoding="utf-8"
            )
            check = checker.BoundaryCheck(root, root / "manifest")
            resolved = check.resolve_stdlib_module("foo/bar", root / "src")
            self.assertEqual([path.name for path in resolved], ["bar.xu"])
            self.assertFalse(check.errors)

    def test_primer_exceptions_are_registered_and_non_product(self) -> None:
        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        check = checker.BoundaryCheck(
            ROOT, BOOTSTRAP_ROOT / "BOUNDARY.json", strict_freeze=True
        )
        check.run(manifest)
        self.assertFalse(check.errors, repr(check.errors))
        report = check.info["primer_exceptions"]
        self.assertEqual(report["unregistered_untracked"], [])
        self.assertGreaterEqual(report["entries"], 4)
        for section in ("experimental_primer_slices", "auxiliary_bootstrap_slices"):
            for entry in manifest[section]:
                self.assertFalse(entry["product_evidence"])
                self.assertTrue(entry["sync_id"].startswith("SYNC-"))

    def test_product_and_oracle_consumers_are_disjoint(self) -> None:
        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        check = checker.BoundaryCheck(
            ROOT, BOOTSTRAP_ROOT / "BOUNDARY.json", strict_freeze=True
        )
        check.run(manifest)
        self.assertFalse(check.errors, repr(check.errors))
        product = set(manifest["product_consumers"])
        orchestrators = {
            entry["path"] for entry in manifest["product_orchestrators"]
        }
        oracle = set(manifest["oracle_consumers"]["paths"])
        self.assertTrue({
            "scripts/cli_platform_test.sh",
            "scripts/deploy_xu_server.sh",
        } <= product)
        self.assertTrue({
            "scripts/deploy_xu_remote.sh",
            "scripts/pack_macos_ui_app.py",
        } <= orchestrators)
        self.assertTrue(product.isdisjoint(oracle))
        self.assertTrue(orchestrators.isdisjoint(oracle))

    def test_oracle_consumers_have_executable_boundary_markers(self) -> None:
        """Oracle role must survive shell-script refactors, not just comments."""

        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        check = checker.BoundaryCheck(
            ROOT, BOOTSTRAP_ROOT / "BOUNDARY.json", strict_freeze=True
        )
        check.run(manifest)
        self.assertFalse(check.errors, repr(check.errors))
        expected = set(manifest["oracle_consumers"]["paths"])
        self.assertEqual(set(check.info["oracle_lane_annotations"]), expected)
        for rel in sorted(expected):
            text = (ROOT / rel).read_text(encoding="utf-8")
            active = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            self.assertRegex(
                active,
                r"(?m)^[ \t]*BOUNDARY_LANE[ \t]*=[ \t]*(?:oracle|['\"]oracle['\"])[ \t]*$",
                rel,
            )

    def test_direct_oracle_consumers_use_strict_seed_resolver(self) -> None:
        """Fixed-path oracle harnesses must reject aliases and arbitrary binaries."""

        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        check = checker.BoundaryCheck(
            ROOT, BOOTSTRAP_ROOT / "BOUNDARY.json", strict_freeze=True
        )
        check.run(manifest)
        self.assertFalse(check.errors, repr(check.errors))
        expected = set(manifest["invariants"]["oracle_strict_resolver_scripts"])
        self.assertEqual(set(check.info["oracle_strict_resolver_scripts"]), expected)
        for rel in sorted(expected):
            text = (ROOT / rel).read_text(encoding="utf-8")
            active = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            self.assertIn("XU_REQUIRE_FROZEN_PRIMER=1", active, rel)
            self.assertIn("XU_ALLOW_ORACLE_SEED=1", active, rel)
            self.assertIn("xu_host_seed.sh", active, rel)

    def test_oracle_consumers_have_executable_boundary_markers(self) -> None:
        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        paths = sorted(manifest["oracle_consumers"]["paths"])
        check = checker.BoundaryCheck(
            ROOT, BOOTSTRAP_ROOT / "BOUNDARY.json", strict_freeze=True
        )
        check.run(manifest)
        self.assertFalse(check.errors, repr(check.errors))
        self.assertEqual(check.info["oracle_lane_annotations"], paths)
        for rel in paths:
            text = (ROOT / rel).read_text(encoding="utf-8")
            active = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            self.assertRegex(
                active,
                r"(?im)^[ \t]*BOUNDARY_LANE[ \t]*=[ \t]*(?:['\"]oracle['\"]|oracle)[ \t]*(?:#.*)?$",
                rel,
            )

    def test_lane_aware_product_probe_is_not_a_compiler_consumer(self) -> None:
        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        check = checker.BoundaryCheck(
            ROOT, BOOTSTRAP_ROOT / "BOUNDARY.json", strict_freeze=True
        )
        check.run(manifest)
        self.assertFalse(check.errors, repr(check.errors))
        probes = manifest["product_probes"]
        self.assertEqual(probes["lane"], "product")
        self.assertTrue(probes["explicit_only"])
        self.assertIn("scripts/xu_doctor.py", probes["paths"])
        self.assertNotIn("scripts/xu_doctor.py", manifest["product_consumers"])

    def test_boundary_infrastructure_is_registered(self) -> None:
        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        check = checker.BoundaryCheck(
            ROOT, BOOTSTRAP_ROOT / "BOUNDARY.json", strict_freeze=True
        )
        check.run(manifest)
        self.assertFalse(check.errors, repr(check.errors))
        kinds = {
            entry["kind"] for entry in manifest["boundary_infrastructure"]["paths"]
        }
        self.assertEqual(
            kinds,
            {
                "seed-resolver",
                "generation-orchestrator",
                "product-wrapper",
                "policy-checker",
                "source-manifest",
                "top-level-entrypoints",
            },
        )
        self.assertEqual(
            set(check.info["boundary_infrastructure"]),
            {entry["path"] for entry in manifest["boundary_infrastructure"]["paths"]},
        )

    def test_boundary_definition_and_gate_files_are_required(self) -> None:
        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        required = set(manifest["required_paths"])
        self.assertTrue(
            {
                "bootstrap/BOUNDARY.json",
                "Makefile",
                "scripts/check_bootstrap_xu_boundary.py",
                "tests/test_bootstrap_boundary_contract.py",
                "docs/audit/BOOTSTRAP_XU_BOUNDARY.md",
                "scripts/build_platform_xu.sh",
            } <= required
        )

    def test_seed_resolving_product_regressions_are_explicit(self) -> None:
        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        check = checker.BoundaryCheck(
            ROOT, BOOTSTRAP_ROOT / "BOUNDARY.json", strict_freeze=True
        )
        check.run(manifest)
        self.assertFalse(check.errors, repr(check.errors))
        expected = {
            "scripts/product_math_x64_test.sh",
            "scripts/product_algorithm_x64_test.sh",
            "scripts/tls_cross_compile_test.sh",
            "scripts/tls_interop_test.sh",
            "scripts/x509_revocation_test.sh",
            "scripts/check_crypto_constant_time_codegen.py",
        }
        cfg = manifest["product_seed_consumers"]
        self.assertEqual(set(cfg["paths"]), expected)
        self.assertEqual(cfg["lane"], "product")
        self.assertTrue(cfg["explicit_only"])
        self.assertEqual(set(check.info["product_seed_consumers"]), expected)

        # Keep the source-level seam visible even if a script's implementation
        # is later refactored: each direct product regression must name the
        # resolver, the hermetic runner, and the oracle-off switch.
        for rel in sorted(expected):
            text = (ROOT / rel).read_text(encoding="utf-8")
            active = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            self.assertRegex(active, r"\bLANE\s*=\s*[\"']product[\"']", rel)
            self.assertIn("HOST_SEED_RESOLVER", active, rel)
            self.assertIn("run_product_compiler.sh", active, rel)
            self.assertIn("XU_ALLOW_ORACLE_SEED=0", active, rel)

    def test_mixed_harnesses_are_explicitly_dual_lane(self) -> None:
        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        check = checker.BoundaryCheck(
            ROOT, BOOTSTRAP_ROOT / "BOUNDARY.json", strict_freeze=True
        )
        check.run(manifest)
        self.assertFalse(check.errors, repr(check.errors))
        cfg = manifest["dual_consumers"]
        self.assertEqual(cfg["lane"], "dual")
        self.assertTrue(cfg["explicit_only"])
        self.assertTrue(
            {
                "scripts/scheduler_stress.py",
                "scripts/language_eval.py",
            } <= set(cfg["paths"])
        )
        self.assertEqual(
            set(cfg["product_compile_paths"]),
            {
                "scripts/programs_cross_check.sh",
                "scripts/run_fixtures.sh",
                "scripts/platform_test.sh",
                "scripts/scheduler_stress.py",
            },
        )
        for rel in ("scripts/scheduler_stress.py", "scripts/language_eval.py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            active = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            self.assertRegex(active, r"\bLANE\s*=\s*[\"']dual[\"']", rel)
        for rel in cfg["product_compile_paths"]:
            text = (ROOT / rel).read_text(encoding="utf-8")
            active = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            self.assertIn("HOST_SEED_RESOLVER", active, rel)
            self.assertIn("PRODUCT_COMPILER_RUNNER", active, rel)
            self.assertIn("run_product_compiler.sh", active, rel)

    def test_chain_contains_oracle_artifact_isolation_guard(self) -> None:
        chain = (ROOT / "scripts" / "build_hosted_chain.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('XU_ALLOW_ORACLE_INSTALL', chain)
        self.assertIn("oracle artifact kept", chain)
        self.assertLess(
            chain.index("oracle artifact kept"),
            chain.index("./scripts/build_product_tools.sh"),
        )

    def test_oracle_workflow_is_explicit_and_registered(self) -> None:
        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        self.assertIn(".github/workflows/oracle.yml", manifest["required_paths"])
        workflow = (ROOT / ".github/workflows/oracle.yml").read_text(encoding="utf-8")
        active = "\n".join(
            line for line in workflow.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertRegex(workflow, r"(?im)^\s*name:\s*oracle\b")
        self.assertIn("XU_CI_LANE=oracle", active)
        self.assertRegex(active, r"\bmake\s+oracle\b")
        self.assertNotRegex(active, r"\bmake\s+(?:xu|product-selfhost|selfhost)\b")

        check = checker.BoundaryCheck(
            ROOT, BOOTSTRAP_ROOT / "BOUNDARY.json", strict_freeze=True
        )
        check.run(manifest)
        self.assertFalse(check.errors, repr(check.errors))
        self.assertIn(".github/workflows/oracle.yml", check.info["ci_lane_annotations"])

    def test_user_docs_do_not_offer_implicit_bootstrap_fallback(self) -> None:
        docs = [
            *sorted((ROOT / "developer" / "examples").glob("*/README.md")),
            ROOT / "developer" / "xu_mail" / "README.md",
            *([project_root("vscode") / "LSP.md"] if (project_root("vscode") / "LSP.md").is_file() else []),
        ]
        for path in docs:
            text = path.read_text(encoding="utf-8")
            # The old one-line ``# 或 ./bootstrap/...`` examples silently
            # blurred product and primer lanes.  Any remaining primer command
            # must sit beside an explicit oracle/recovery explanation.
            self.assertNotRegex(
                text,
                r"#\s*(?:或|or)\s+\.?/?bootstrap/target",
                str(path),
            )
            has_primer = "bootstrap/target" in text or "cargo build --manifest-path bootstrap" in text
            if has_primer:
                self.assertRegex(
                    text,
                    r"(?i)oracle|recovery",
                    str(path),
                )
            if has_primer and path.name != "LSP.md":
                self.assertIn("run_product_compiler.sh", text, str(path))

    def test_product_source_does_not_direct_users_to_primer(self) -> None:
        """Executable product messages must not restore a Gen0 fallback."""

        manifest = checker.load_manifest(BOOTSTRAP_ROOT / "BOUNDARY.json")
        check = checker.BoundaryCheck(
            ROOT, BOOTSTRAP_ROOT / "BOUNDARY.json", strict_freeze=True
        )
        check.run(manifest)
        self.assertFalse(check.errors, repr(check.errors))
        self.assertTrue(manifest["invariants"]["product_source_must_not_reference_primer"])
        source = (ROOT / "src" / "cmd" / "compile" / "driver_entry.xu").read_text(
            encoding="utf-8"
        )
        self.assertNotRegex(source, r"bootstrap\s+(?:xu|primer)\b")

    def test_oracle_lane_rejects_arbitrary_executables(self) -> None:
        """Every Python oracle selector must stay anchored to Gen0."""

        scheduler = self._load_script_module(
            "xu_scheduler_boundary", "scripts/scheduler_stress.py"
        )
        with self.assertRaises(ValueError):
            scheduler._resolve_oracle_compiler("/bin/echo")

        doctor = self._load_script_module("xu_doctor_boundary", "scripts/xu_doctor.py")
        self.assertFalse(doctor._is_frozen_primer(Path("/bin/echo")))

    def test_python_guards_reject_primer_symlinks_and_aliases(self) -> None:
        """Resolving a symlink must not erase its bootstrap provenance."""

        modules = [
            (
                self._load_script_module("xu_scheduler_symlink_boundary", "scripts/scheduler_stress.py"),
                "_is_frozen_primer",
            ),
            (
                self._load_script_module("xu_crypto_symlink_boundary", "scripts/check_crypto_constant_time_codegen.py"),
                "is_frozen_primer",
            ),
            (
                self._load_script_module("xu_doctor_symlink_boundary", "scripts/xu_doctor.py"),
                "_is_frozen_primer",
            ),
            (
                self._load_script_module("xu_language_eval_symlink_boundary", "scripts/language_eval.py"),
                "is_frozen_primer",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            debug = root / "bootstrap" / "target" / "debug"
            debug.mkdir(parents=True)
            # A symlink at the declared artifact must never be accepted, even
            # when its target is an executable.  A second alias exercises the
            # parent-component check for callers that canonicalise too early.
            (debug / "xu").symlink_to("/bin/echo")
            alias_parent = Path(tmp) / "bootstrap-alias"
            alias_parent.symlink_to(root / "bootstrap")
            alias = alias_parent / "target" / "debug" / "xu"
            for module, name in modules:
                old_root = module.ROOT
                old_frozen = getattr(module, "FROZEN_PRIMER_PATHS", None)
                try:
                    module.ROOT = root
                    module.FROZEN_PRIMER_PATHS = frozenset(
                        {
                            (root / "bootstrap" / "target" / "debug" / "xu").absolute(),
                            (root / "bootstrap" / "target" / "debug" / "xu.exe").absolute(),
                            (root / "bootstrap" / "target" / "release" / "xu").absolute(),
                            (root / "bootstrap" / "target" / "release" / "xu.exe").absolute(),
                        }
                    )
                    guard = getattr(module, name)
                    self.assertFalse(guard(debug / "xu"), module.__name__)
                    self.assertFalse(guard(alias), module.__name__)
                finally:
                    module.ROOT = old_root
                    if old_frozen is not None:
                        module.FROZEN_PRIMER_PATHS = old_frozen

    def test_language_eval_portability_uses_selected_product(self) -> None:
        module = self._load_script_module(
            "xu_language_eval_product_portability", "scripts/language_eval.py"
        )
        product = ROOT / "bin" / "xu"
        command, _ = module.command_for(
            module.BY_NAME["portability"], xu=product, report_dir=ROOT / "target",
            quick=False, iters=7, benches=None, discard_first=False,
        )
        self.assertEqual(command, ["./scripts/platform_test.sh", f"--xu={product}",
                                   "--lane=product"])

    def test_language_eval_primer_flag_skips_symlink_and_finds_release_artifact(self) -> None:
        """The dual orchestrator must pass only a physical frozen primer downstream."""

        module = self._load_script_module(
            "xu_language_eval_primer_boundary", "scripts/language_eval.py"
        )
        with tempfile.TemporaryDirectory() as tmp:
            # Keep the synthetic root physical as the production module does;
            # macOS commonly exposes /var as a symlink to /private/var.
            root = (Path(tmp) / "repo").resolve()
            debug = root / "bootstrap" / "target" / "debug"
            release = root / "bootstrap" / "target" / "release"
            debug.mkdir(parents=True)
            release.mkdir(parents=True)
            (debug / "xu").symlink_to("/bin/echo")
            release_xu = release / "xu"
            release_xu.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            release_xu.chmod(0o755)
            old_root = module.ROOT
            old_candidates = module._BOOT_CANDIDATES
            old_frozen = module.FROZEN_PRIMER_PATHS
            try:
                module.ROOT = root
                module._BOOT_CANDIDATES = (
                    debug / "xu",
                    debug / "xu.exe",
                    release / "xu",
                    release / "xu.exe",
                )
                module.FROZEN_PRIMER_PATHS = frozenset(
                    candidate.absolute() for candidate in module._BOOT_CANDIDATES
                )
                self.assertEqual(module.primer_flag(), [f"--xu={release_xu}"])
            finally:
                module.ROOT = old_root
                module._BOOT_CANDIDATES = old_candidates
                module.FROZEN_PRIMER_PATHS = old_frozen

    def test_python_primer_classifier_resolves_unresolved_alias(self) -> None:
        """One-argument provenance checks must follow aliases for classification."""

        modules = [
            ("xu_primer_alias_language_eval", "scripts/language_eval.py", "is_primer"),
            (
                "xu_primer_alias_crypto",
                "scripts/check_crypto_constant_time_codegen.py",
                "is_primer",
            ),
            ("xu_primer_alias_scheduler", "scripts/scheduler_stress.py", "_is_primer"),
        ]
        loaded = [
            (self._load_script_module(name, relative), function)
            for name, relative, function in modules
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = (Path(tmp) / "repo").resolve()
            primer = root / "bootstrap" / "target" / "debug" / "xu"
            primer.parent.mkdir(parents=True)
            primer.write_text("primer", encoding="utf-8")
            alias_parent = Path(tmp) / "bootstrap-alias"
            alias_parent.symlink_to(root / "bootstrap")
            alias = alias_parent / "target" / "debug" / "xu"
            traversed = root / "bin" / ".." / "bootstrap" / "target" / "debug" / "xu"
            (root / "bin").mkdir()
            for module, function_name in loaded:
                old_root = module.ROOT
                try:
                    module.ROOT = root
                    classifier = getattr(module, function_name)
                    self.assertTrue(classifier(alias), module.__name__)
                    self.assertTrue(classifier(traversed), module.__name__)
                finally:
                    module.ROOT = old_root

    def test_json_report_exposes_machine_status_and_errors(self) -> None:
        proc = subprocess.run(
            [
                "python3",
                str(CHECKER_PATH),
                "--strict-freeze",
                "--json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])
        self.assertIn("source_manifest", report["checks"])
        self.assertIn("repo_head", report)

    def test_product_wrapper_rejects_primer_and_outside_package_roots(self) -> None:
        wrapper = ROOT / "scripts" / "run_product_compiler.sh"
        primer = BOOTSTRAP_ROOT / "target" / "debug" / "xu"
        primer_run = subprocess.run(
            [str(wrapper), str(primer), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(primer_run.returncode, 0)
        self.assertIn("primer", primer_run.stderr.lower())

        # /bin/echo is only a harmless executable stand-in: this test checks
        # the wrapper's path policy before it reaches a real compiler.
        with tempfile.TemporaryDirectory() as outside:
            outside_run = subprocess.run(
                [str(wrapper), "/bin/echo", "build"],
                cwd=ROOT,
                env={**os.environ, "XU_PRODUCT_XUPATH": outside},
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(outside_run.returncode, 0)
        self.assertIn("XU_PRODUCT_XUPATH", outside_run.stderr)

        bootstrap_run = subprocess.run(
            [str(wrapper), "/bin/echo", "build", "probe"],
            cwd=ROOT,
            env={**os.environ, "XU_PRODUCT_XUPATH": str(ROOT / "bootstrap")},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(bootstrap_run.returncode, 0)
        self.assertIn("frozen bootstrap", bootstrap_run.stderr)

    def test_product_wrapper_accepts_valid_controlled_package_root(self) -> None:
        wrapper = ROOT / "scripts" / "run_product_compiler.sh"
        valid_run = subprocess.run(
            [str(wrapper), "/bin/echo", "build", "probe"],
            cwd=ROOT,
            env={**os.environ, "XU_PRODUCT_XUPATH": str(ROOT / "src")},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(valid_run.returncode, 0, valid_run.stderr)
        self.assertIn("build probe", valid_run.stdout)

    def test_product_wrapper_explicit_cwd_keeps_isolation(self) -> None:
        wrapper = ROOT / "scripts" / "run_product_compiler.sh"
        with tempfile.TemporaryDirectory(prefix="xu-cwd-with spaces-") as directory:
            # Harmless executable stand-in, as above: exercise wrapper policy,
            # output placement and cleanup without a compiler/selfhost build.
            result = subprocess.run([str(wrapper), "--cwd", directory, "/bin/sh", "-c",
                'test -z "$XUPATH" && test -z "${XUOS:-}" && '
                'test -d "$XU_CACHE" && pwd -P > relative-output && printf "%s" "$XU_CACHE"'],
                cwd=ROOT, env={**os.environ, "XUPATH": "/invalid-shadow", "XUOS": "windows"},
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((Path(directory) / "relative-output").read_text().strip(),
                             str(Path(directory).resolve()))
            self.assertFalse(Path(result.stdout).exists(), "isolated cache must be reclaimed")
        for directory in ("relative-directory", "/xu-no-such-cwd-directory"):
            result = subprocess.run([str(wrapper), "--cwd", directory, "/bin/echo", "build"],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--cwd", result.stderr)

    def test_platform_copy_rejects_primer_before_native_copy(self) -> None:
        """A native-target copy is still a product-boundary operation."""

        script = ROOT / "scripts" / "build_platform_xu.sh"
        primer = BOOTSTRAP_ROOT / "target" / "debug" / "xu"
        with tempfile.TemporaryDirectory() as out:
            proc = subprocess.run(
                [str(script), str(primer), out],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("hosted product seed", proc.stderr.lower())


if __name__ == "__main__":
    unittest.main()
