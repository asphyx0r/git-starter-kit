"""Exercise the blocking npm audit wrapper without a dependency install."""

from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fixture_cleanup import cleanup_temporary_directory


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/quality/npm-security.py"
spec = importlib.util.spec_from_file_location("npm_security", SCRIPT)
assert spec is not None and spec.loader is not None
security = importlib.util.module_from_spec(spec)
spec.loader.exec_module(security)


def clean_report():
    return {
        "auditReportVersion": 2,
        "vulnerabilities": {},
        "metadata": {
            "vulnerabilities": {
                "info": 0,
                "low": 0,
                "moderate": 0,
                "high": 0,
                "critical": 0,
                "total": 0,
            }
        },
    }


def high_report():
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
                        "url": "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm",
                        "severity": "high",
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


class NpmAuditPolicyTests(unittest.TestCase):
    def test_all_high_findings_block_without_an_exemption(self):
        report = high_report()
        result = security.evaluate_audit(report)
        self.assertEqual(result["rawReport"], report)
        self.assertEqual(result["rawCounts"]["high"], 2)
        self.assertEqual(result["blocked"], ["braces", "micromatch"])
        self.assertEqual(set(result), {"rawReport", "rawCounts", "blocked"})

    def test_critical_findings_block(self):
        report = high_report()
        report["vulnerabilities"]["braces"]["severity"] = "critical"
        report["metadata"]["vulnerabilities"].update(high=1, critical=1)
        self.assertEqual(
            security.evaluate_audit(report)["blocked"], ["braces", "micromatch"]
        )

    def test_lower_severities_are_reported_without_blocking(self):
        for severity in ("info", "low", "moderate"):
            with self.subTest(severity=severity):
                report = high_report()
                for record in report["vulnerabilities"].values():
                    record["severity"] = severity
                report["vulnerabilities"]["braces"]["via"][0]["severity"] = severity
                report["metadata"]["vulnerabilities"].update(high=0, **{severity: 2})
                result = security.evaluate_audit(report)
                self.assertEqual(result["rawCounts"][severity], 2)
                self.assertEqual(result["blocked"], [])

    def test_clean_report_has_no_blockers(self):
        report = clean_report()
        self.assertEqual(
            security.evaluate_audit(report),
            {
                "rawReport": report,
                "rawCounts": report["metadata"]["vulnerabilities"],
                "blocked": [],
            },
        )

    def test_invalid_report_shape_or_registry_errors_fail_closed(self):
        for report in (
            None,
            [],
            "invalid",
            {},
            dict(clean_report(), auditReportVersion=2.0),
            dict(clean_report(), auditReportVersion=True),
            dict(clean_report(), auditReportVersion=3),
            dict(clean_report(), vulnerabilities=[]),
            dict(clean_report(), error={"message": "registry unavailable"}),
            dict(clean_report(), error=None),
        ):
            with self.subTest(report=report), self.assertRaises(ValueError):
                security.evaluate_audit(report)

    def test_invalid_record_fields_fail_closed(self):
        for field, value in (
            ("name", "wrong"),
            ("severity", "unknown"),
            ("severity", []),
            ("nodes", []),
            ("nodes", "node_modules/braces"),
            ("nodes", [None]),
            ("nodes", [""]),
            ("via", []),
            ("via", {}),
            ("via", [None]),
            ("via", [""]),
            ("via", [{}]),
            ("via", [{"name": "braces", "url": "", "severity": "high"}]),
            (
                "via",
                [{"name": "other", "url": "https://example.com", "severity": "high"}],
            ),
            ("via", [{"name": "braces", "url": "https://example.com", "severity": []}]),
        ):
            with self.subTest(field=field, value=value):
                report = high_report()
                report["vulnerabilities"]["braces"][field] = value
                with self.assertRaises(ValueError):
                    security.evaluate_audit(report)
        for record in (None, []):
            report = high_report()
            report["vulnerabilities"]["braces"] = record
            with self.subTest(record=record), self.assertRaises(ValueError):
                security.evaluate_audit(report)

    def test_missing_or_cyclic_attribution_fails_closed(self):
        for change in ("missing", "cycle"):
            with self.subTest(change=change):
                report = high_report()
                if change == "missing":
                    report["vulnerabilities"]["micromatch"]["via"] = ["absent"]
                else:
                    report["vulnerabilities"]["braces"]["via"] = ["micromatch"]
                with self.assertRaises(ValueError):
                    security.evaluate_audit(report)

    def test_counts_require_exact_nonnegative_integer_values(self):
        for field, value in (
            ("info", False),
            ("high", 2.0),
            ("high", 1),
            ("total", -1),
        ):
            report = high_report()
            report["metadata"]["vulnerabilities"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                security.evaluate_audit(report)
        for metadata in (None, {}, {"vulnerabilities": []}):
            report = high_report()
            report["metadata"] = metadata
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                security.evaluate_audit(report)


class NpmSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="npm-audit-regression-")
        self.addCleanup(cleanup_temporary_directory, self.temporary)
        self.root = Path(self.temporary.name)
        self.quality = self.root / "quality"
        self.quality.mkdir()
        self.npm_cli = self.root / "npm-cli.js"
        self.request = self.quality / "request.json"
        self.write_cli(json.dumps(clean_report()))

    def write_cli(self, payload, *, exit_code=0, stderr="", body=""):
        # A controlled Python child exercises the real containment and npm argv.
        self.npm_cli.write_text(
            "import json, os, subprocess, sys, time\n"
            "from pathlib import Path\n"
            "arguments = sys.argv[1:]\n"
            "cache = Path(arguments[arguments.index('--cache') + 1])\n"
            "(cache / 'probe').write_text('cache writable')\n"
            f"Path({str(self.request)!r}).write_text(json.dumps({{\n"
            "    'arguments': arguments,\n"
            "    'cache': str(cache),\n"
            "    'ignoreScripts': os.environ.get('NPM_CONFIG_IGNORE_SCRIPTS'),\n"
            "}))\n"
            f"{body}\n"
            f"print({payload!r})\n"
            f"print({stderr!r}, file=sys.stderr)\n"
            f"raise SystemExit({exit_code})\n",
            encoding="utf-8",
        )

    @contextmanager
    def cli_runtime(self):
        with (
            patch.object(
                security.shutil,
                "which",
                side_effect=lambda name: (
                    sys.executable if name == "node" else str(self.npm_cli)
                ),
            ),
            patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": "1"}),
        ):
            yield

    def captured_request(self):
        request = json.loads(self.request.read_text())
        self.assertFalse(Path(request["cache"]).exists(), "Audit cache was retained")
        return request

    def test_registered_cleanup_retries_transient_windows_directory_deletion(self):
        failure = OSError("pending Windows deletion")
        failure.winerror = 145
        original = tempfile.TemporaryDirectory._rmtree
        calls = 0

        def remove(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise failure
            return original(*args, **kwargs)

        cleanup, arguments, keywords = self._cleanups[0]
        with patch.object(tempfile.TemporaryDirectory, "_rmtree", side_effect=remove):
            try:
                cleanup(*arguments, **keywords)
            except OSError as error:
                self.fail(f"Transient cleanup error escaped: {error}")
        self.assertEqual(calls, 2)
        self.assertFalse(Path(self.temporary.name).exists())

    def test_registered_cleanup_preserves_persistent_and_other_errors(self):
        cleanup, arguments, keywords = self._cleanups[0]
        for winerror, expected_calls in ((145, 3), (5, 1), (None, 1)):
            with self.subTest(winerror=winerror):
                failure = OSError("cleanup failed")
                if winerror is not None:
                    failure.winerror = winerror
                with (
                    patch.object(
                        tempfile.TemporaryDirectory, "_rmtree", side_effect=failure
                    ) as remove,
                    self.assertRaises(OSError) as caught,
                ):
                    cleanup(*arguments, **keywords)
                self.assertIs(caught.exception, failure)
                self.assertEqual(remove.call_count, expected_calls)

    def test_removed_commands_are_rejected_by_the_parser(self):
        for command in ("patch", "verify"):
            with self.subTest(command=command), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    security.main([command, "--quality-root", str(self.quality)])
                self.assertEqual(caught.exception.code, 2)

    def test_help_and_version_need_no_runtime(self):
        for arguments in (["--help"], ["audit", "--help"], ["--version"]):
            with (
                self.subTest(arguments=arguments),
                patch.object(
                    security.shutil,
                    "which",
                    side_effect=AssertionError("Help must not inspect runtimes"),
                ),
                redirect_stdout(io.StringIO()) as output,
                self.assertRaises(SystemExit) as caught,
            ):
                security.main(arguments)
            self.assertEqual(caught.exception.code, 0)
            self.assertTrue(output.getvalue())

    def test_dry_run_needs_no_installed_patch_and_creates_nothing(self):
        before = {
            path.name: path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        for arguments in (["--dry-run", "audit"], ["audit", "--dry-run"]):
            with (
                self.subTest(arguments=arguments),
                self.cli_runtime(),
                patch.object(
                    security.tempfile,
                    "TemporaryDirectory",
                    side_effect=AssertionError("Dry run must not create a cache"),
                ),
                patch.object(
                    security.subprocess,
                    "Popen",
                    side_effect=AssertionError("Dry run must not launch npm"),
                ),
                redirect_stdout(io.StringIO()) as output,
            ):
                status = security.main(
                    [*arguments, "--quality-root", str(self.quality)]
                )
                self.assertEqual(status, 0)
                report = json.loads(output.getvalue())
                self.assertTrue(report["dryRun"])
                self.assertIn("--audit-level=high", report["command"])
        self.assertEqual(
            {
                path.name: path.read_bytes()
                for path in self.root.rglob("*")
                if path.is_file()
            },
            before,
        )

    def test_clean_audit_needs_no_installed_patch(self):
        with self.cli_runtime():
            result = security.audit(self.quality)
        self.assertEqual(result["rawReport"], clean_report())
        self.assertEqual(result["blocked"], [])
        self.assertEqual(list(self.quality.iterdir()), [self.request])
        self.captured_request()

    def test_audit_command_uses_isolated_cache_and_disables_scripts(self):
        caches = []
        for _ in range(2):
            with self.cli_runtime():
                security.audit(self.quality)
            request = self.captured_request()
            cache = request["cache"]
            caches.append(cache)
            self.assertEqual(
                request["arguments"],
                [
                    "audit",
                    "--json",
                    "--include=dev",
                    "--audit-level=high",
                    "--prefix",
                    str(self.quality),
                    "--cache",
                    cache,
                ],
            )
            self.assertEqual(request["ignoreScripts"], "true")
            self.assertFalse(Path(cache).is_relative_to(self.quality))
        self.assertNotEqual(caches[0], caches[1])

    def test_main_returns_audit_policy_status_for_npm_exit_zero_or_one(self):
        for report, npm_status, expected_status in (
            (clean_report(), 0, 0),
            (clean_report(), 1, 0),
            (high_report(), 1, 1),
        ):
            with self.subTest(npm_status=npm_status, expected_status=expected_status):
                self.write_cli(json.dumps(report), exit_code=npm_status)
                with (
                    self.cli_runtime(),
                    redirect_stdout(io.StringIO()) as output,
                    redirect_stderr(io.StringIO()) as errors,
                ):
                    status = security.main(
                        ["audit", "--quality-root", str(self.quality)]
                    )
                self.assertEqual(status, expected_status)
                self.assertEqual(json.loads(output.getvalue())["rawReport"], report)
                self.assertEqual(errors.getvalue(), "")
                self.captured_request()

    def test_invalid_json_registry_error_and_other_exit_status_fail_closed(self):
        for payload, exit_code in (
            ("invalid json", 0),
            (json.dumps({"error": {"code": "EAI_AGAIN"}}), 1),
            (json.dumps(clean_report()), 2),
        ):
            with self.subTest(payload=payload, exit_code=exit_code):
                self.write_cli(
                    payload, exit_code=exit_code, stderr="registry unavailable"
                )
                with self.cli_runtime(), self.assertRaises(ValueError):
                    security.audit(self.quality)
                self.captured_request()

    def test_main_failure_is_controlled_and_verbose_preserves_the_exception(self):
        self.write_cli("invalid json")
        with (
            self.cli_runtime(),
            redirect_stdout(io.StringIO()) as output,
            redirect_stderr(io.StringIO()) as errors,
        ):
            status = security.main(["audit", "--quality-root", str(self.quality)])
        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("npm security:", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())
        self.captured_request()
        with self.cli_runtime(), self.assertRaises(ValueError):
            security.main(["-v", "audit", "--quality-root", str(self.quality)])
        self.captured_request()

    def test_missing_node_npm_or_cli_fails_before_creating_a_cache(self):
        for node, npm in (
            (None, str(self.npm_cli)),
            (sys.executable, None),
            (sys.executable, str(self.root / "missing.js")),
        ):
            with (
                self.subTest(node=node, npm=npm),
                patch.object(
                    security.shutil,
                    "which",
                    side_effect=lambda name: node if name == "node" else npm,
                ),
                patch.object(
                    security.tempfile,
                    "TemporaryDirectory",
                    side_effect=AssertionError(
                        "Invalid runtime must not create a cache"
                    ),
                ),
                self.assertRaises(ValueError),
            ):
                security.audit(self.quality)
        self.assertEqual(list(self.quality.iterdir()), [])

    def test_timeout_contains_descendants_with_inherited_pipes_and_cleans_cache(self):
        ready = self.quality / "descendant.ready"
        survived = self.quality / "descendant.survived"
        child = (
            "from pathlib import Path; import time; "
            f"Path({str(ready)!r}).write_text('ready'); "
            "time.sleep(5); "
            f"Path({str(survived)!r}).write_text('survived')"
        )
        body = (
            f"subprocess.Popen([sys.executable, '-B', '-c', {child!r}])\n"
            f"while not Path({str(ready)!r}).exists(): time.sleep(0.01)"
        )
        self.write_cli(json.dumps(clean_report()), body=body)
        with (
            self.cli_runtime(),
            patch.object(security, "AUDIT_TIMEOUT_SECONDS", 4),
            self.assertRaises(subprocess.TimeoutExpired) as caught,
        ):
            security.audit(self.quality)
        self.assertTrue(
            ready.is_file(),
            f"Descendant did not start: {caught.exception.output!r} {caught.exception.stderr!r}",
        )
        self.captured_request()
        time.sleep(2.3)
        self.assertFalse(survived.exists(), "Descendant escaped audit containment")


if __name__ == "__main__":
    unittest.main()
