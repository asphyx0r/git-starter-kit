from __future__ import annotations

import importlib.util
import copy
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "tools/automation_config.py"


class AutomationConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(ADAPTER.is_file(), "Shared automation adapter is missing")
        sys.path.insert(0, str(ROOT / "tools"))
        self.addCleanup(sys.path.remove, str(ROOT / "tools"))
        spec = importlib.util.spec_from_file_location("automation_config", ADAPTER)
        self.adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.adapter)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def configured(self, enabled):
        value = {
            "schemaVersion": 1,
            "repositoryRole": "project",
            "releaseKind": "repository",
            "automations": dict.fromkeys(
                ("agentRulesSync", "guardedMerge", "releasePreflight"), enabled
            ),
            "checks": [],
        }
        (self.root / ".starter-kit-project.json").write_text(json.dumps(value))

    def test_disabled_sync_blocks_every_automatic_event_but_allows_manual(self):
        self.configured(False)
        for event in ("release", "schedule", "push", "repository_dispatch"):
            with self.subTest(event=event):
                self.assertFalse(
                    self.adapter.automation_enabled(
                        self.root, "agentRulesSync", event=event, legacy_sync="true"
                    )
                )
        self.assertTrue(
            self.adapter.automation_enabled(
                self.root,
                "agentRulesSync",
                event="workflow_dispatch",
                legacy_sync="false",
            )
        )

    def test_configured_json_is_single_authority_and_other_manual_flags_stay_off(self):
        self.configured(True)
        self.assertTrue(
            self.adapter.automation_enabled(
                self.root, "agentRulesSync", event="schedule", legacy_sync="false"
            )
        )
        self.configured(False)
        for name in ("guardedMerge", "releasePreflight"):
            self.assertFalse(
                self.adapter.automation_enabled(
                    self.root, name, event="workflow_dispatch"
                )
            )

    def test_legacy_release_and_variable_behavior_are_preserved(self):
        for event, variable, expected in (
            ("release", "false", True),
            ("schedule", "false", False),
            ("schedule", "", True),
            ("workflow_dispatch", "false", False),
        ):
            with self.subTest(event=event, variable=variable):
                self.assertEqual(
                    self.adapter.automation_enabled(
                        self.root, "agentRulesSync", event=event, legacy_sync=variable
                    ),
                    expected,
                )
        self.assertTrue(
            self.adapter.automation_enabled(
                self.root, "guardedMerge", event="repository_dispatch"
            )
        )

    def test_invalid_configuration_fails_even_for_manual_sync(self):
        (self.root / ".starter-kit-project.json").write_text('{"schemaVersion": 1}')
        with self.assertRaises(ValueError):
            self.adapter.automation_enabled(
                self.root, "agentRulesSync", event="workflow_dispatch"
            )
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ADAPTER),
                "--repository-root",
                str(self.root),
                "--automation",
                "agentRulesSync",
                "--event",
                "release",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("enabled=", result.stdout)
        self.assertIn("Configuration", result.stderr)

    def test_canonical_source_defaults_keep_all_automations_and_deployment(self):
        value = json.loads((ROOT / ".starter-kit-project.json").read_text())
        self.assertEqual(value["repositoryRole"], "source")
        self.assertEqual(value["releaseKind"], "deployment")
        self.assertEqual(value["checks"], [])
        self.assertTrue(all(value["automations"].values()))

    def test_remote_activation_uses_one_immutable_default_snapshot_not_local_config(
        self,
    ):
        self.configured(True)
        remote = json.loads((self.root / ".starter-kit-project.json").read_text())
        remote["automations"]["guardedMerge"] = False
        sha, tree, blob = "a" * 40, "b" * 40, "c" * 40
        calls = []

        def read_json(arguments):
            calls.append(arguments)
            return {
                "repos/owner/repo/commits/main": {
                    "sha": sha,
                    "commit": {"tree": {"sha": tree}},
                },
                f"repos/owner/repo/git/trees/{tree}": {
                    "sha": tree,
                    "truncated": False,
                    "tree": [
                        {
                            "path": ".starter-kit-project.json",
                            "mode": "100644",
                            "type": "blob",
                            "sha": blob,
                        }
                    ],
                },
                f"repos/owner/repo/git/blobs/{blob}": {
                    "encoding": "base64",
                    "sha": blob,
                    "content": base64.b64encode(json.dumps(remote).encode()).decode(),
                },
            }[arguments[-1]]

        with (
            mock.patch(
                "tempfile.TemporaryDirectory",
                side_effect=AssertionError("remote gate must not create temp"),
            ),
            mock.patch.object(
                Path,
                "write_bytes",
                side_effect=AssertionError("remote gate must not write"),
            ),
        ):
            self.assertFalse(
                self.adapter.remote_guarded_merge_enabled(
                    "owner/repo", "main", read_json
                )
            )
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1][-1], f"repos/owner/repo/git/trees/{tree}")
        self.assertEqual(calls[2][-1], f"repos/owner/repo/git/blobs/{blob}")

    def test_remote_legacy_missing_file_and_invalid_tree_are_distinct(self):
        sha, tree = "a" * 40, "b" * 40

        def read_json(arguments):
            if arguments[-1].endswith("commits/main"):
                return {"sha": sha, "commit": {"tree": {"sha": tree}}}
            return {"sha": tree, "truncated": False, "tree": []}

        self.assertTrue(
            self.adapter.remote_guarded_merge_enabled("owner/repo", "main", read_json)
        )
        with self.assertRaises(ValueError):
            self.adapter.remote_guarded_merge_enabled(
                "owner/repo", "main", lambda args: {}
            )

    def test_remote_wrong_tree_identity_is_rejected_before_legacy_fallback(self):
        responses = iter(
            [
                {"sha": "a" * 40, "commit": {"tree": {"sha": "b" * 40}}},
                {"sha": "c" * 40, "truncated": False, "tree": []},
            ]
        )
        with self.assertRaises(ValueError):
            self.adapter.remote_guarded_merge_enabled(
                "owner/repo", "main", lambda args: next(responses)
            )

    def test_remote_malformed_transfer_and_configuration_fail_without_writes(self):
        self.configured(False)
        value = json.loads((self.root / ".starter-kit-project.json").read_text())
        base = [
            {"sha": "a" * 40, "commit": {"tree": {"sha": "b" * 40}}},
            {
                "sha": "b" * 40,
                "truncated": False,
                "tree": [
                    {
                        "path": ".starter-kit-project.json",
                        "mode": "100644",
                        "type": "blob",
                        "sha": "c" * 40,
                    }
                ],
            },
            {
                "sha": "c" * 40,
                "encoding": "base64",
                "content": base64.b64encode(json.dumps(value).encode()).decode(),
            },
        ]
        for index, field, replacement in (
            (0, "sha", "invalid"),
            (1, "truncated", True),
            (2, "sha", "d" * 40),
            (2, "encoding", "utf-8"),
            (2, "content", "%%%"),
            (2, "content", "é"),
            (2, "content", base64.b64encode(b"{}").decode()),
        ):
            responses = copy.deepcopy(base)
            responses[index][field] = replacement
            values = iter(responses)
            with (
                self.subTest(index=index, field=field, replacement=replacement),
                self.assertRaises(ValueError),
            ):
                self.adapter.remote_guarded_merge_enabled(
                    "owner/repo", "main", lambda args: next(values)
                )
        for mode in ("120000", "040000"):
            responses = copy.deepcopy(base)
            responses[1]["tree"][0]["mode"] = mode
            values = iter(responses)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.adapter.remote_guarded_merge_enabled(
                    "owner/repo", "main", lambda args: next(values)
                )


if __name__ == "__main__":
    unittest.main()
