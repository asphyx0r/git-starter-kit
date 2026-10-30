"""Keep historical repair maintenance files out of consumer distributions."""

import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

import test_build_release_package as package_tests
from test_starter_kit_manifest import MANIFEST


REPAIR_PATHS = (
    "tools/historical-release-repair.py",
    ".github/workflows/historical-release-repair.yml",
)


class HistoricalReleaseDistributionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_tracked_repair_files_are_excluded_from_manifest_and_zip(self):
        package = package_tests.BuildReleasePackageTests()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = package.create_package_repository(root)
            for relative in REPAIR_PATHS:
                target = repository / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("source-only repair fixture\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "--", *REPAIR_PATHS],
                cwd=repository,
                check=True,
                capture_output=True,
            )
            manifest_paths = {
                entry["path"] for entry in MANIFEST.core_entries(repository, None)
            }
            self.assertIn("tools/release-artifacts.py", manifest_paths)
            for relative in REPAIR_PATHS:
                self.assertNotIn(relative, manifest_paths)

            output = root / "output"
            result = package.run_package(
                package_tests.SCRIPT_PATH, output, repository_root=repository
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(output / "existing.zip") as archive:
                managed_paths = {
                    entry["path"]
                    for entry in json.loads(archive.read("_starter-kit-files.json"))[
                        "files"
                    ]
                }
                self.assertIn("tools/release-artifacts.py", archive.namelist())
                for relative in REPAIR_PATHS:
                    self.assertNotIn(relative, archive.namelist())
                    self.assertNotIn(relative, managed_paths)
