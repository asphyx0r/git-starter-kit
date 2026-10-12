"""Exercise attested npm fixes without suppressing unrelated advisories."""

from __future__ import annotations

import json
import importlib.util
import base64
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / "tools/quality"
SCRIPT = QUALITY / "npm-security.py"
spec = importlib.util.spec_from_file_location("npm_security", SCRIPT)
assert spec is not None and spec.loader is not None
security = importlib.util.module_from_spec(spec)
spec.loader.exec_module(security)


class NpmSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.quality = Path(self.temporary.name) / "quality"
        package = self.quality / "node_modules/braces"
        package.parent.mkdir(parents=True)
        archive_path = ROOT / "tests/fixtures/braces-3.0.3.tgz"
        source_integrity = "sha512-" + base64.b64encode(
            hashlib.sha512(archive_path.read_bytes()).digest()
        ).decode("ascii")
        provenance = json.loads(
            (QUALITY / "patches/braces-3.0.3/manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(source_integrity, provenance["sourceIntegrity"])
        source_names = ("compile.js", "expand.js", "stringify.js", "utils.js")
        shutil.copytree(
            QUALITY / "node_modules/braces",
            package,
            ignore=shutil.ignore_patterns(*source_names),
        )
        with tarfile.open(archive_path, "r:gz") as archive:
            for name in source_names:
                member = archive.extractfile(f"package/lib/{name}")
                assert member is not None
                with member:
                    (package / "lib" / name).write_bytes(member.read())
        self.package = package
        (self.quality / "package-lock.json").write_text(
            json.dumps(
                {
                    "packages": {
                        "node_modules/braces": json.loads(
                            (QUALITY / "package-lock.json").read_text(encoding="utf-8")
                        )["packages"]["node_modules/braces"]
                    }
                }
            ),
            encoding="utf-8",
        )

    def cli(self, command, *arguments):
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                command,
                "--quality-root",
                str(self.quality),
                *arguments,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def node(self, script):
        environment = dict(os.environ, NODE_PATH=str(QUALITY / "node_modules"))
        return subprocess.run(
            ["node", "-e", script, str(self.package)],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )

    def test_patch_preserves_brace_expansion_and_compilation(self):
        result = self.cli("patch")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.node(
            "const b=require(process.argv[1]); "
            "console.log(JSON.stringify([b.expand('src/{a,b}/{1..2}.md'), "
            "b.compile('src/{a,b}.md'), "
            "b.expand('{a,a,b}',{nodupes:true})]));"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            [
                ["src/a/1.md", "src/a/2.md", "src/b/1.md", "src/b/2.md"],
                "src/(a|b).md",
                ["a", "b"],
            ],
        )

    def test_patched_walkers_support_deep_patterns_without_stack_exhaustion(self):
        result = self.cli("patch")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.node(
            "const b=require(process.argv[1]); "
            "const pattern='{'.repeat(4000)+'x'+'}'.repeat(4000); "
            "const ast=b.parse(pattern); "
            "if(b.stringify(ast)!==pattern || b.compile(pattern)!==pattern || "
            "JSON.stringify(b.expand(pattern))!==JSON.stringify([pattern])) "
            "throw new Error('deep pattern semantics changed');"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_patch_is_idempotent_and_verify_rejects_tampering(self):
        result = self.cli("patch")
        self.assertEqual(result.returncode, 0, result.stderr)
        first = {p.name: p.read_bytes() for p in self.package.glob("lib/*.js")}
        result = self.cli("patch")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            first, {p.name: p.read_bytes() for p in self.package.glob("lib/*.js")}
        )
        result = self.cli("verify")
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.package / "lib/compile.js").write_bytes(b"unexpected code\n")
        result = self.cli("verify")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("compile.js", result.stderr)

    def test_patch_matches_upstream_for_patterns_and_options(self):
        original = self.quality / "original"
        shutil.copytree(self.package, original)
        self.assertEqual(self.cli("patch").returncode, 0)
        result = self.node(
            "const b=require(process.argv[1]), old=require(process.argv[1]+'/../../original');"
            "const patterns=['','a','{}','{a,b}','{,a,}','{a,,b}',"
            "'{a,{b,c},d}','x{1..5..2}y','{-3..3}','{01..03}','{c..a}',"
            "'{a..9}','{a,b}{c,d}','${a,b}','{a,b','a,b}',"
            "'\\\\{a,b}','{a,\\\\,b}','[a{b,c}]','{a,{,b}}','{1..2000}'];"
            "let seed=41;const chars='abc{},.[]\\\\';"
            "for(let i=0;i<200;i++){let p='';for(let j=0;j<18;j++){"
            "seed=(Math.imul(seed,1664525)+1013904223)>>>0;"
            "p+=chars[seed%chars.length];}patterns.push(p);}"
            "const capture=f=>{try{return ['ok',f()]}catch(e){return ['error',e.name,e.message]}};"
            "for(const p of patterns)for(const opts of [{},{escapeInvalid:true},"
            "{nodupes:true,noempty:true},{keepEscaping:true},{rangeLimit:5}])"
            "for(const method of ['compile','expand','stringify']){"
            "const run=x=>x[method](method==='stringify'?x.parse(p,opts):p,opts);"
            "const a=JSON.stringify(capture(()=>run(old))),c=JSON.stringify(capture(()=>run(b)));"
            "if(a!==c)throw Error(JSON.stringify({p,opts,method,a,c}));}"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dry_run_and_failed_patch_preserve_original_files(self):
        before = {p.name: p.read_bytes() for p in self.package.glob("lib/*.js")}
        self.assertEqual(self.cli("patch", "--dry-run").returncode, 0)
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.package.glob("lib/*.js")}
        )
        replace = security.replace_file
        calls = 0

        def interrupt(path, content, mode):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt("simulated interruption")
            replace(path, content, mode)

        with patch.object(security, "replace_file", side_effect=interrupt):
            with self.assertRaisesRegex(KeyboardInterrupt, "simulated"):
                security.patch(self.quality)
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.package.glob("lib/*.js")}
        )
        self.assertEqual({p.name for p in self.package.glob("lib/*")}, set(before))

    def test_all_nested_locked_occurrences_must_be_attested(self):
        nested = self.quality / "node_modules/other/node_modules/braces"
        shutil.copytree(self.package, nested)
        lock_path = self.quality / "package-lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["packages"][nested.relative_to(self.quality).as_posix()] = dict(
            lock["packages"]["node_modules/braces"]
        )
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        self.assertEqual(self.cli("patch").returncode, 0)
        self.assertEqual(len(security.verify(self.quality)), 2)
        (nested / "index.js").write_bytes(b"tampered\n")
        self.assertNotEqual(self.cli("verify").returncode, 0)

    def test_unlocked_occurrence_cannot_be_overlooked(self):
        shutil.copytree(
            self.package, self.quality / "node_modules/other/node_modules/braces"
        )
        result = self.cli("patch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unlocked", result.stderr.lower())

    def test_linked_package_and_wrong_source_integrity_are_rejected(self):
        lock_path = self.quality / "package-lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["packages"]["node_modules/braces"]["integrity"] = "sha512-wrong"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        self.assertNotEqual(self.cli("patch").returncode, 0)

    def test_unknown_bytes_are_rejected_before_any_write(self):
        compile_path = self.package / "lib/compile.js"
        original = compile_path.read_bytes()
        (self.package / "lib/expand.js").write_bytes(b"unknown\n")
        self.assertNotEqual(self.cli("patch").returncode, 0)
        self.assertEqual(compile_path.read_bytes(), original)

    def test_rollback_preserves_a_concurrent_foreign_change(self):
        replace = security.replace_file
        first = None
        interrupted = False

        def interrupt(path, content, mode):
            nonlocal first, interrupted
            if first is None:
                first = path
                replace(path, content, mode)
            elif not interrupted:
                interrupted = True
                first.unlink()
                first.write_bytes(b"foreign edit\n")
                raise KeyboardInterrupt("simulated interruption")
            else:
                replace(path, content, mode)

        with patch.object(security, "replace_file", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt) as failure:
                security.patch(self.quality)
        self.assertIsNotNone(first)
        self.assertEqual(first.read_bytes(), b"foreign edit\n")
        self.assertIn("rollback incomplete", " ".join(failure.exception.__notes__))

    def test_cleanup_failure_keeps_the_original_replacement_error(self):
        with patch.object(
            security.os, "replace", side_effect=OSError("replace failed")
        ):
            with patch.object(Path, "unlink", side_effect=OSError("cleanup failed")):
                with self.assertRaisesRegex(OSError, "replace failed") as failure:
                    security.replace_file(self.package / "index.js", b"content", 0o644)
        self.assertIn("cleanup failed", " ".join(failure.exception.__notes__))


class NpmAuditPolicyTests(unittest.TestCase):
    def report(self):
        return {
            "auditReportVersion": 2,
            "vulnerabilities": {
                "braces": {
                    "name": "braces",
                    "severity": "high",
                    "nodes": ["node_modules/braces"],
                    "via": [
                        {
                            "name": "braces",
                            "url": "https://github.com/advisories/" + security.ADVISORY,
                        }
                    ],
                },
                "micromatch": {
                    "name": "micromatch",
                    "severity": "high",
                    "nodes": ["node_modules/micromatch"],
                    "via": ["braces"],
                },
            },
            "metadata": {
                "vulnerabilities": {
                    "info": 0,
                    "low": 0,
                    "moderate": 0,
                    "high": 2,
                    "critical": 0,
                    "total": 2,
                }
            },
        }

    def evaluate(self, report):
        return security.evaluate_audit(report, {"node_modules/braces"})

    def test_only_attested_braces_leaves_can_clear_the_high_gate(self):
        result = self.evaluate(self.report())
        self.assertEqual(result["rawCounts"]["high"], 2)
        self.assertEqual(result["attested"], ["braces", "micromatch"])
        self.assertEqual(result["blocked"], [])

    def test_unknown_advisory_mixed_into_a_chain_is_blocked(self):
        report = self.report()
        report["vulnerabilities"]["micromatch"]["via"].append(
            {"name": "micromatch", "url": "https://github.com/advisories/GHSA-other"}
        )
        self.assertEqual(self.evaluate(report)["blocked"], ["micromatch"])

    def test_missing_or_cyclic_attribution_and_registry_errors_fail_closed(self):
        for change in ("missing", "cycle", "empty", "error", "counts"):
            with self.subTest(change=change):
                report = self.report()
                if change == "missing":
                    report["vulnerabilities"]["micromatch"]["via"] = ["absent"]
                elif change == "cycle":
                    report["vulnerabilities"]["braces"]["via"] = ["micromatch"]
                elif change == "empty":
                    report["vulnerabilities"]["braces"]["via"] = []
                elif change == "error":
                    report["error"] = {"message": "registry unavailable"}
                else:
                    report["metadata"]["vulnerabilities"]["high"] = 0
                with self.assertRaises(ValueError):
                    self.evaluate(report)

    def test_unattested_nodes_and_critical_advisories_stay_blocking(self):
        report = self.report()
        report["vulnerabilities"]["braces"]["nodes"].append(
            "node_modules/other/node_modules/braces"
        )
        self.assertEqual(self.evaluate(report)["blocked"], ["braces", "micromatch"])
        report = self.report()
        report["vulnerabilities"]["braces"]["severity"] = "critical"
        report["metadata"]["vulnerabilities"].update(high=1, critical=1)
        self.assertEqual(self.evaluate(report)["blocked"], ["braces", "micromatch"])


if __name__ == "__main__":
    unittest.main()
