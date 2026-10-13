"""Verify external SQL drivers through the product compiler, without a database."""
import os
import re
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get('XU', str(REPO / 'bin/xu'))).resolve()
import sys
sys.path.insert(0, str(REPO / 'scripts'))
from companion_repos import project_root
PACKAGES = project_root('packages')


class SqlDriverBoundary(unittest.TestCase):
    def compile(self, source, output, flags=()):
        env = dict(os.environ, XUPATH='', XU_CACHE=str(output.parent / 'cache'))
        for key in ('XUOS', 'XUARCH', 'XU_HEAP_STATS'):
            env.pop(key, None)
        return subprocess.run([str(XU), 'build', str(source), *flags, '-o', str(output)],
                              cwd=REPO, env=env, capture_output=True, text=True, timeout=90)

    def test_dsn_fixtures_use_external_drivers(self):
        for name in ('mysql', 'postgres'):
            fixture = REPO / f'tests/fixtures/database_sql_{name}'
            for flags in (('-O0',), ('-O3',)):
                with self.subTest(driver=name, flags=flags), tempfile.TemporaryDirectory() as path:
                    output = Path(path) / 'probe'
                    work = Path(path) / 'project'
                    shutil.copytree(fixture, work)
                    (work / 'xu.xun').write_text('module: sql_boundary\nversion: !ver 0.1.0\nrequire:\n' + f'  "github.com/xulang-org/packages": file:{PACKAGES}\n')
                    compiled = self.compile(work, output, flags)
                    self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                    result = subprocess.run([str(output)], capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(result.stdout, (fixture / 'expected.txt').read_text())

    def test_sql_examples_compile_with_manifest_dependencies(self):
        for directory in ('17_database_postgres', '18_database_mysql'):
            with self.subTest(example=directory), tempfile.TemporaryDirectory() as path:
                name = directory.split('_')[-1]
                work = Path(path) / 'project'
                shutil.copytree(REPO / 'tests/data/sql_examples' / name, work)
                (work / 'xu.xun').write_text('module: sql_boundary\nversion: !ver 0.1.0\nrequire:\n' + f'  "github.com/xulang-org/packages": file:{PACKAGES}\n')
                compiled = self.compile(work, Path(path) / 'example')
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)

    def test_driver_readme_examples_compile(self):
        for name in ('mysql', 'postgres'):
            with self.subTest(driver=name), tempfile.TemporaryDirectory() as path:
                work = Path(path)
                readme = (PACKAGES / name / 'README.md').read_text()
                source = re.search(r'```xu\n(.*?)\n```', readme, re.S).group(1)
                (work / 'main.xu').write_text(source)
                (work / 'xu.xun').write_text('module: sql_boundary\nversion: !ver 0.1.0\nrequire:\n'
                                           f'  "github.com/xulang-org/packages": file:{PACKAGES}\n')
                compiled = self.compile(work, work / 'probe')
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)

    def test_both_drivers_share_the_sql_api_in_one_application(self):
        with tempfile.TemporaryDirectory() as path:
            work = Path(path)
            (work / 'xu.xun').write_text('module: sql_boundary\nversion: !ver 0.1.0\nrequire:\n'
                                       f'  "github.com/xulang-org/packages": file:{PACKAGES}\n')
            (work / 'main.xu').write_text('@main\n#database/sql\nmysql #github.com/xulang-org/packages/mysql\npostgres #github.com/xulang-org/packages/postgres\n'
                'fn main() int {\n'
                '    mut my := sql.open(mysql.driver(), "")\n'
                '    mut pg := sql.open(postgres.driver(), "")\n'
                '    my.close() or (err) { println(err.msg())\n        << 1 }\n'
                '    pg.close() or (err) { println(err.msg())\n        << 1 }\n'
                '    println("both drivers use sql.DB")\n    << 0\n}\n')
            output = work / 'probe'
            compiled = self.compile(work, output)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(output)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout, 'both drivers use sql.DB\n')

    def test_external_drivers_require_explicit_dependency(self):
        for name in ('mysql', 'postgres'):
            with self.subTest(driver=name), tempfile.TemporaryDirectory() as path:
                work = Path(path)
                (work / 'xu.xun').write_text('module: sql_boundary\nversion: !ver 0.1.0\n')
                (work / 'main.xu').write_text(f'@main\n{name} #github.com/xulang-org/packages/{name}\nfn main() {{ _ := {name}.driver() }}\n')
                compiled = self.compile(work, work / 'probe')
                self.assertNotEqual(compiled.returncode, 0)
                self.assertIn(name, compiled.stderr)
                self.assertRegex(compiled.stderr, r'(not found|cannot (load|find|resolve)|require)')

    def test_legacy_imports_do_not_load_a_second_driver(self):
        for name in ('mysql', 'postgres'):
            with self.subTest(driver=name), tempfile.TemporaryDirectory() as path:
                work = Path(path)
                (work / 'xu.xun').write_text('module: sql_boundary\nversion: !ver 0.1.0\nrequire:\n'
                                           f'  "github.com/xulang-org/packages": file:{PACKAGES}\n')
                (work / 'main.xu').write_text(f'@main\n#database/sql/{name}\nfn main() {{}}\n')
                compiled = self.compile(work, work / 'probe')
                self.assertNotEqual(compiled.returncode, 0)
                self.assertIn(f'database/sql/{name}', compiled.stderr)
                self.assertRegex(compiled.stderr, r'(not found|cannot (load|find|resolve))')


if __name__ == '__main__':
    unittest.main()
