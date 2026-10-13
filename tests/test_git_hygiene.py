"""Exercise the local commit gate against real Git indexes in disposable repos."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.check_git_hygiene import check

ROOT = Path(__file__).resolve().parents[1]


class GitHygieneTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="xu-git-hygiene-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git("init", "--quiet")
        self.git("config", "user.name", "Hygiene test")
        self.git("config", "user.email", "hygiene@example.invalid")
        self.git("config", "core.hooksPath", ".githooks")
        self.write(".gitignore", (ROOT / ".gitignore").read_bytes())
        self.write("main.xu", b"original source\n")
        self.git("add", "--", ".gitignore", "main.xu")
        self.git("commit", "--quiet", "-m", "initial source")

    def git(self, *args, check_result=True):
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=check_result,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_forced_docs_and_logs_are_rejected(self):
        self.write("docs/report.md", b"local report\n")
        self.write("result.log", b"run output\n")
        self.git("add", "-f", "--", "docs/report.md", "result.log")
        errors, count = check(self.root)
        self.assertEqual(count, 2)
        self.assertTrue(any("docs/report.md" in error for error in errors))
        self.assertTrue(any("result.log" in error for error in errors))

    def test_historical_docs_require_untracking_and_remain_local(self):
        report = self.write("docs/report.md", b"keep local\n")
        self.git("add", "-f", "--", "docs/report.md")
        self.git("commit", "--quiet", "-m", "legacy report")
        self.write("main.xu", b"new source\n")
        self.git("add", "--", "main.xu")
        self.assertTrue(check(self.root)[0])
        self.git("rm", "--cached", "--", "docs/report.md")
        self.assertEqual(check(self.root)[0], [])
        self.assertEqual(report.read_bytes(), b"keep local\n")

    def test_binary_check_reads_staged_content(self):
        for index, magic in enumerate((b"\x7fELF", b"\xcf\xfa\xed\xfe", b"MZ")):
            name = f"generated{index}"
            self.write(name, magic + b"\0" * 100)
            self.git("add", "--", name)
            self.write(name, b"worktree text\n")
        errors, _ = check(self.root)
        self.assertEqual(len(errors), 3)
        self.assertTrue(all("编译二进制" in error for error in errors))

    def test_sync_debt_ledger_must_remain_local(self):
        ledger = self.write("bootstrap/SYNC_DIFF.md", b"local sync debt\n")
        self.git("add", "-f", "--", "bootstrap/SYNC_DIFF.md")
        self.git("commit", "--quiet", "-m", "legacy ledger")
        errors, _ = check(self.root)
        self.assertTrue(any("bootstrap/SYNC_DIFF.md" in error for error in errors))
        self.git("rm", "--cached", "--", "bootstrap/SYNC_DIFF.md")
        self.assertEqual(check(self.root)[0], [])
        self.assertEqual(ledger.read_bytes(), b"local sync debt\n")

    def test_unstaged_local_files_do_not_affect_clean_commit(self):
        self.write("docs/report.md", b"local\n")
        self.write("untracked-probe.xu", b"scratch\n")
        self.write("main.xu", b"staged source\n")
        self.git("add", "--", "main.xu")
        self.write("main.xu", b"unstaged source with trailing spaces   \n")
        self.assertEqual(check(self.root), ([], 1))

    def test_formal_stderr_golden_is_allowed(self):
        self.write("tests/fixtures/error/expected.stderr", b"expected diagnostic\n")
        self.git("add", "--", "tests/fixtures/error/expected.stderr")
        self.assertEqual(check(self.root), ([], 1))

    def test_base32_text_golden_is_allowed(self):
        self.write("tests/fixtures/base32/expected.txt", b"MZXW6YTBOI======\n")
        self.git("add", "--", "tests/fixtures/base32/expected.txt")
        self.assertEqual(check(self.root), ([], 1))

    def test_new_ignored_output_path_is_rejected(self):
        with (self.root / ".gitignore").open("a") as stream:
            stream.write("/local-output.json\n")
        self.write("local-output.json", b"{}\n")
        self.git("add", "--", ".gitignore")
        self.git("add", "-f", "--", "local-output.json")
        self.assertTrue(any("local-output.json" in error for error in check(self.root)[0]))

    def test_large_files_and_staged_whitespace_are_rejected(self):
        self.write("large.dat", b"x" * (10 * 1024 * 1024 + 1))
        self.write("main.xu", b"trailing whitespace   \n")
        self.git("add", "--", "large.dat", "main.xu")
        errors, _ = check(self.root)
        self.assertTrue(any("10 MiB" in error for error in errors))
        self.assertTrue(any("trailing whitespace" in error for error in errors))

    def test_installed_hook_blocks_real_commit(self):
        for name in ("scripts/check_git_hygiene.py", ".githooks/pre-commit"):
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
        self.write("docs/report.md", b"local\n")
        self.git("add", "-f", "--", "docs/report.md")
        result = self.git("commit", "-m", "must fail", check_result=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Git 提交检查失败".encode(), result.stderr)
        self.assertEqual(self.git("log", "-1", "--format=%s").stdout.strip(), b"initial source")


if __name__ == "__main__":
    unittest.main()
