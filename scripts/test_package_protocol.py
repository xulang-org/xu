#!/usr/bin/env python3
"""Local package protocol regressions through the product Xu CLI.

Requires Python cryptography (independent Ed25519 signer) and curl. All modules,
HTTP endpoints, signed checkpoints, proof tiles and caches are disposable.
Run: python3 scripts/test_package_protocol.py --compiler bin/xu
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_platform_runtime import compiler_env

COMPILER: Path
MODULE = "protocol.test/value"
VERSION = "v1.0.0"


def sha(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def source_key(module: str, version: str) -> str:
    return sha(f"xu-source-v2\n{len(module)}:{module}{len(version)}:{version}".encode()).hex()


def tree_hash(files: dict[str, bytes]) -> str:
    # Independent sha256-tree-v1 encoder; nested directories are supported.
    def record(directory: str) -> bytes:
        prefix = directory + "/" if directory else ""
        names = sorted({path[len(prefix):].split("/")[0] for path in files if path.startswith(prefix)})
        result = f"D{len(directory)}:{directory}\n".encode()
        for name in names:
            path = prefix + name
            if path in files:
                result += f"F{len(path)}:{path}:{sha(files[path]).hex()}\n".encode()
            else:
                result += record(path)
        return result
    return sha(b"xu-tree-v1\n" + record("")).hex()


def manifest(module: str, version: str, requires: dict[str, str] | None = None) -> bytes:
    text = f"module: {module}\nversion: !ver {version.removeprefix('v')}\n"
    if requires:
        text += "require:\n" + "".join(f"  {key}: {value}\n" for key, value in requires.items())
    return text.encode()


def module_files(module: str = MODULE, version: str = VERSION, value: int = 42,
                 requires: dict[str, str] | None = None) -> dict[str, bytes]:
    return {"xu.xun": manifest(module, version, requires),
            "mod.xu": f'@"{module}"\npub fn value() int {{ << {value} }}\n'.encode()}


def proxy_routes(module: str, version: str, files: dict[str, bytes]) -> dict[str, tuple[int, bytes]]:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
        for name, body in files.items():
            output.writestr(f"{module}@{version}/{name}", body)
    prefix = f"/{module}/@v/{version}"
    return {prefix + ".info": (200, json.dumps({"Version": version}).encode()),
            prefix + ".mod": (200, files["xu.xun"]), prefix + ".zip": (200, archive.getvalue())}


class LocalServer:
    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, bytes]] = {}
        self.requests: list[str] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                owner.requests.append(self.path)
                status, body = owner.routes.get(self.path, (404, b"missing"))
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self) -> LocalServer:
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class SumDB:
    def __init__(self, entries: list[tuple[str, str, str]]) -> None:
        # Fixed test-only seed; never a production credential.
        self.signer = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        key = b"\x01" + self.signer.public_key().public_bytes_raw()
        self.name = "sumdb.protocol.test"
        self.key_hash = sha(self.name.encode() + b"\n" + key)[:4]
        self.verifier = f"{self.name}+{self.key_hash.hex()}+{base64.b64encode(key).decode()}"
        self.texts = [f"{module} {version} sha256-tree-v1:{digest}\n".encode() for module, version, digest in entries]
        leaves = [sha(b"\x00" + text) for text in self.texts]

        def root(nodes: list[bytes]) -> bytes:
            if len(nodes) == 1:
                return nodes[0]
            split = 1 << ((len(nodes) - 1).bit_length() - 1)
            return sha(b"\x01" + root(nodes[:split]) + root(nodes[split:]))

        self.note = self.checkpoint(len(entries), root(leaves))
        self.routes = {f"/lookup/{module}@{version}": (200, str(i).encode() + b"\n" + self.texts[i] + b"\n" + self.note)
                       for i, (module, version, _) in enumerate(entries)}
        # Small local trees use a single partial level-zero tile.
        self.routes[f"/tile/8/0/000.p/{len(leaves)}"] = (200, b"".join(leaves))

    def checkpoint(self, size: int, root: bytes) -> bytes:
        text = f"go.sum database tree\n{size}\n{base64.b64encode(root).decode()}\n".encode()
        sig = base64.b64encode(self.key_hash + self.signer.sign(text))
        return text + b"\n" + "— ".encode() + self.name.encode() + b" " + sig + b"\n"


class PackageProtocol(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="xu-package-protocol-")
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.project = self.work / "project"
        self.project.mkdir()
        self.cache = self.work / "cache"
        self.env = compiler_env()
        self.env.update(XU_CACHE=str(self.cache), HOME=str(self.work), USERPROFILE=str(self.work),
                        XUSUMDB="off", XUPROXY="off", NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")

    def project_requires(self, requires: dict[str, str], module: str = MODULE) -> None:
        (self.project / "xu.xun").write_bytes(manifest("protocol.test/app", "v1.0.0", requires))
        (self.project / "main.xu").write_text(
            f'@main\n#"{module}" as dep\nfn main() {{ println(dep.value()) }}\n', encoding="utf-8")

    def xu(self, *args: str, error: str | None = None) -> subprocess.CompletedProcess:
        result = subprocess.run([str(COMPILER), *args], cwd=self.project, env=self.env,
                                capture_output=True, timeout=90)
        output = (result.stdout + result.stderr).decode(errors="replace")
        if error is None:
            self.assertEqual(result.returncode, 0, output)
        else:
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn(error, output)
        return result

    def build_run(self, expected: bytes = b"42\n", *flags: str) -> None:
        executable = self.project / "app"
        self.xu("build", "main.xu", *flags, "-o", str(executable))
        result = subprocess.run([str(executable)], cwd=self.project, env=self.env, capture_output=True, timeout=15)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, b""))

    @contextmanager
    def authenticated(self, *, digest: str | None = None):
        files = module_files()
        db = SumDB([(MODULE, VERSION, digest if digest is not None else tree_hash(files)),
                    ("protocol.test/other", VERSION, "b" * 64)])
        with LocalServer() as proxy, LocalServer() as log:
            proxy.routes.update(proxy_routes(MODULE, VERSION, files))
            log.routes.update(db.routes)
            self.env.update(XUPROXY=proxy.url, XUSUMDB=f"{db.verifier} {log.url}")
            self.project_requires({MODULE: VERSION})
            yield db, proxy, log

    def sumdb_root(self, db: SumDB) -> Path:
        return self.cache / "sumdb" / sha(b"xu-sumdb-v1\n" + db.verifier.encode()).hex()

    def test_bad_digest_rejected(self) -> None:
        with self.authenticated(digest="0" * 64) as (_, _, log):
            self.xu("install", error="authenticated module checksum mismatch")
            self.assertIn(f"/lookup/{MODULE}@{VERSION}", log.requests)
            self.assertFalse((self.cache / source_key(MODULE, VERSION) / ".ok").exists())
            self.assertFalse((self.project / "vendor" / MODULE).exists())

    def test_bad_signature_rejected(self) -> None:
        with self.authenticated() as (db, _, log):
            # Preserve canonical base64 and key identity, corrupt signature only.
            lookup = f"/lookup/{MODULE}@{VERSION}"
            payload = log.routes[lookup][1]
            signed = base64.b64decode(payload.split(b" ")[-1])
            corrupt = signed[:4] + bytes([signed[4] ^ 1]) + signed[5:]
            log.routes[lookup] = (200, payload.rsplit(b" ", 1)[0] + b" " + base64.b64encode(corrupt) + b"\n")
            self.xu("install", error="invalid checkpoint signature")
            self.assertFalse((self.sumdb_root(db) / "latest").exists())
            self.assertFalse((self.cache / source_key(MODULE, VERSION) / ".ok").exists())

    def test_mvs_diamond(self) -> None:
        left, right, shared = ("protocol.test/" + name for name in ("left", "right", "shared"))
        with LocalServer() as proxy:
            for module, version, value, requires in (
                (left, VERSION, 1, {shared: "v1.1.0"}),
                (right, VERSION, 2, {shared: "v1.2.0"}),
                (shared, "v1.1.0", 11, None), (shared, "v1.2.0", 12, None),
                (shared, "v1.9.0", 19, None)):
                proxy.routes.update(proxy_routes(module, version, module_files(module, version, value, requires)))
            self.env["XUPROXY"] = proxy.url
            self.project_requires({left: VERSION, right: VERSION}, shared)
            self.xu("install")
            self.build_run(b"12\n")
            lock = (self.project / "xu.lock").read_text()
            for version in ("v1.1.0", "v1.2.0"):
                self.assertIn(f"{shared} {source_key(shared, version)} ", lock)
            selected = self.project / "vendor" / shared / "xu.xun"
            self.assertEqual(selected.read_bytes(), manifest(shared, "v1.2.0"))
            self.assertNotIn(f"/{shared}/@v/v1.9.0.info", proxy.requests)
            shutil.rmtree(self.cache)
            before = list(proxy.requests)
            self.build_run(b"12\n", "--offline")
            self.assertEqual(proxy.requests, before)

    def test_proxy_fallback(self) -> None:
        # Comma falls back only on 404/410; pipe also permits server errors.
        for status, separator, success in ((404, ",", True), (410, ",", True),
                                            (503, ",", False), (503, "|", True)):
            with self.subTest(status=status, separator=separator):
                shutil.rmtree(self.cache, ignore_errors=True)
                shutil.rmtree(self.project / "vendor", ignore_errors=True)
                (self.project / "xu.lock").unlink(missing_ok=True)
                with LocalServer() as first, LocalServer() as second:
                    prefix = f"/{MODULE}/@v/{VERSION}"
                    first.routes[prefix + ".info"] = (status, b"unavailable")
                    second.routes.update(proxy_routes(MODULE, VERSION, module_files()))
                    self.env["XUPROXY"] = first.url + separator + second.url
                    self.project_requires({MODULE: VERSION})
                    self.xu("install", error=None if success else "proxy request failed (status 503)")
                    self.assertEqual(first.requests, [prefix + ".info"])
                    self.assertEqual(second.requests, [prefix + ext for ext in (".info", ".mod", ".zip")] if success else [])
                    if success:
                        self.build_run()

    def test_malformed_success_does_not_fallback(self) -> None:
        with LocalServer() as first, LocalServer() as second:
            routes = proxy_routes(MODULE, VERSION, module_files())
            first.routes.update(routes)
            first.routes[f"/{MODULE}/@v/{VERSION}.info"] = (200, b"not json")
            second.routes.update(routes)
            self.env["XUPROXY"] = first.url + "|" + second.url
            self.project_requires({MODULE: VERSION})
            self.xu("install", error="malformed proxy .info")
            self.assertEqual(second.requests, [])

    def test_vendor_tamper(self) -> None:
        with self.authenticated() as (_, proxy, log):
            self.xu("install")
            self.build_run()
            before = (list(proxy.requests), list(log.requests))
            path = self.project / "vendor" / MODULE / "mod.xu"
            path.write_bytes(path.read_bytes().replace(b"42", b"99"))
            self.xu("build", "main.xu", "--frozen", error="vendor checksum mismatch")
            self.assertEqual((proxy.requests, log.requests), before)

    def test_offline_proof_cache(self) -> None:
        with self.authenticated() as (db, proxy, log):
            self.xu("install")
            root = self.sumdb_root(db)
            self.assertTrue((root / "latest").is_file())
            self.assertTrue(list((root / "nodes").iterdir()))
            # Close both servers: offline success must use persisted proofs.
        before = {str(p.relative_to(self.cache)): p.read_bytes() for p in self.cache.rglob("*") if p.is_file()}
        self.build_run(b"42\n", "--offline")
        self.build_run(b"42\n", "--frozen")
        after = {str(p.relative_to(self.cache)): p.read_bytes() for p in self.cache.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        shutil.rmtree(root / "nodes")
        self.xu("build", "main.xu", "--offline", error="offline/frozen build needs cached proof")

    def test_offline_missing_record(self) -> None:
        with self.authenticated() as (db, _, _):
            self.xu("install")
        (self.sumdb_root(db) / "records" / source_key(MODULE, VERSION)).unlink()
        self.xu("build", "main.xu", "--offline", error="needs cached checksum record")

    def test_forked_checkpoint(self) -> None:
        with self.authenticated() as (db, proxy, log):
            self.xu("install")
            root = self.sumdb_root(db)
            trusted = (root / "latest").read_bytes()
            # A different module/version forces a fresh lookup under the same
            # trusted key. Its valid signature and matching digest must not
            # permit a conflicting root at the already accepted tree size.
            other = "protocol.test/fork"
            files = module_files(other, VERSION, 99)
            fork = SumDB([(MODULE, VERSION, tree_hash(module_files())),
                          (other, VERSION, tree_hash(files))])
            self.assertEqual(fork.verifier, db.verifier)
            log.routes.update(fork.routes)
            proxy.routes.update(proxy_routes(other, VERSION, files))
            self.project_requires({other: VERSION}, other)
            self.xu("install", error="conflicting checkpoint at the same size")
            self.assertEqual((root / "latest").read_bytes(), trusted)
            self.assertFalse((root / "records" / source_key(other, VERSION)).exists())
            self.assertFalse((self.cache / source_key(other, VERSION) / ".ok").exists())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    args, remaining = parser.parse_known_args()
    COMPILER = args.compiler.resolve(strict=True)
    unittest.main(argv=[__file__, *remaining], verbosity=2)
