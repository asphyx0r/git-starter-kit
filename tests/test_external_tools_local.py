"""Qualify explicit local installs and platform variants without network writes."""

from __future__ import annotations

import copy
import ctypes
import hashlib
import inspect
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from test_quality_toolchain import (
    INSTALLER_PATH,
    DECLARED_VERSIONS,
    FakeResponse,
    load_script_module,
    make_zip,
    make_zip_members,
    make_tar,
)


def _process_creation(process_id: int, handle: int | None = None) -> int:
    if sys.platform == "win32":
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.GetProcessTimes.argtypes = [ctypes.c_void_p] + [
            ctypes.POINTER(ctypes.c_uint64)
        ] * 4
        api.GetProcessTimes.restype = ctypes.c_int
        creation, exit_time, kernel_time, user_time = [
            ctypes.c_uint64() for _ in range(4)
        ]
        if not api.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return creation.value
    return int(
        Path(f"/proc/{process_id}/stat")
        .read_text(encoding="utf-8")
        .rsplit(")", 1)[1]
        .split()[19]
    )


def _stop_attested_child(process_id: int, expected_creation: int) -> None:
    if sys.platform == "win32":
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        api.OpenProcess.restype = ctypes.c_void_p
        api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        api.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        # Retain termination, query and synchronization rights on this kernel object.
        handle = api.OpenProcess(0x101001, False, process_id)
        if not handle:
            if ctypes.get_last_error() == 87:
                return
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if _process_creation(process_id, handle) != expected_creation:
                raise ValueError("Process identity changed; refusing termination")
            if api.WaitForSingleObject(handle, 0) != 0:
                if not api.TerminateProcess(handle, 1):
                    if api.WaitForSingleObject(handle, 0) != 0:
                        raise ctypes.WinError(ctypes.get_last_error())
                if api.WaitForSingleObject(handle, 5000) != 0:
                    raise TimeoutError(
                        "Attested child did not terminate within 5 seconds"
                    )
        finally:
            if not api.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())
        return
    try:
        descriptor = os.pidfd_open(process_id)
    except ProcessLookupError:
        return
    try:
        try:
            creation = _process_creation(process_id)
        except FileNotFoundError:
            return
        if creation != expected_creation:
            raise ValueError("Process identity changed; refusing termination")
        if not select.select([descriptor], [], [], 0)[0]:
            try:
                signal.pidfd_send_signal(descriptor, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if not select.select([descriptor], [], [], 5)[0]:
                raise TimeoutError("Attested child did not terminate within 5 seconds")
    finally:
        os.close(descriptor)


class LocalInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.installer = load_script_module(INSTALLER_PATH, "local_installer_test")
        self.registry = copy.deepcopy(DECLARED_VERSIONS)

    def install(self, root: Path, **overrides: object) -> None:
        payload = b"fake pinned executable"
        record = self.registry["external"]["shfmt"]
        record["sha256"] = hashlib.sha256(payload).hexdigest()
        options = {
            "platform_name": "linux-x64",
            "install_root": root,
            "local": True,
            "tool_names": ["shfmt"],
            "open_url": lambda request, **unused: FakeResponse(
                payload, request.full_url
            ),
            "run_command": lambda command, **unused: subprocess.CompletedProcess(
                command, 0, "v3.14.0\n", ""
            ),
        }
        options.update(overrides)
        with mock.patch.object(
            self.installer, "native_platform", return_value="linux-x64"
        ):
            self.installer.install_tools(self.registry, **options)

    def test_local_install_without_runner_temp_publishes_only_selected_tool(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            parent = Path(temporary)
            self.install(parent / "chosen")
            self.assertEqual([path.name for path in parent.iterdir()], ["chosen"])
            self.assertEqual(
                [path.name for path in (parent / "chosen/bin").iterdir()], ["shfmt"]
            )

    def test_local_dry_run_never_downloads_probes_or_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            opener, runner = mock.Mock(), mock.Mock()
            self.install(
                parent / "chosen", dry_run=True, open_url=opener, run_command=runner
            )
            self.assertEqual(list(parent.iterdir()), [])
            opener.assert_not_called()
            runner.assert_not_called()

    def test_local_roots_require_absent_target_and_existing_safe_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            existing = parent / "existing"
            existing.mkdir()
            cases = [
                (existing, "already exist"),
                (parent / "missing/tools", "parent must exist"),
                (parent / "bad/../tools", "unsafe install root"),
            ]
            for root, diagnostic in cases:
                with (
                    self.subTest(root=root),
                    self.assertRaisesRegex(self.installer.InstallerError, diagnostic),
                ):
                    self.install(root, dry_run=True)
            self.assertEqual(list(parent.iterdir()), [existing])

    def test_local_reparse_parent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            with mock.patch.object(
                self.installer, "_is_link", side_effect=lambda path: path == parent
            ):
                with self.assertRaisesRegex(
                    self.installer.InstallerError, "symlink or junction"
                ):
                    self.install(parent / "chosen", dry_run=True)

    def test_real_link_parent_is_rejected_on_native_platform(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            real = parent / "real"
            real.mkdir()
            link = parent / "link"
            if sys.platform == "win32":
                environment = os.environ.copy()
                environment["QUALITY_TEST_LINK"] = str(link)
                environment["QUALITY_TEST_TARGET"] = str(real)
                environment["POWERSHELL_TELEMETRY_OPTOUT"] = "1"
                environment["PSModuleAnalysisCachePath"] = str(parent / "module-cache")
                result = subprocess.run(
                    [
                        "pwsh",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        "New-Item -ItemType Junction -Path $env:QUALITY_TEST_LINK -Target $env:QUALITY_TEST_TARGET | Out-Null",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=environment,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            else:
                link.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(
                self.installer.InstallerError, "symlink or junction"
            ):
                self.install(link / "chosen", dry_run=True)
            self.assertEqual(list(real.iterdir()), [])

    def test_ci_default_still_requires_runner_and_rejects_outside_roots_without_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            runner = parent / "runner"
            runner.mkdir()
            for options, diagnostic in [
                ({}, "RUNNER_TEMP is required"),
                ({"runner_temp": runner}, "strictly under RUNNER_TEMP"),
            ]:
                with self.assertRaisesRegex(self.installer.InstallerError, diagnostic):
                    self.installer.install_tools(
                        self.registry,
                        install_root=parent / "outside",
                        platform_name="linux-x64",
                        tool_names=["shfmt"],
                        dry_run=True,
                        **options,
                    )
            environment = os.environ.copy()
            environment.pop("RUNNER_TEMP", None)
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(INSTALLER_PATH),
                    "--dry-run",
                    "--platform",
                    "linux-x64",
                    "--install-root",
                    str(runner / "chosen"),
                    "--tool",
                    "shfmt",
                ],
                capture_output=True,
                text=True,
                env=environment,
                timeout=10,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("RUNNER_TEMP is required", result.stderr)
            self.assertEqual(list(parent.iterdir()), [runner])
            self.assertEqual(list(runner.iterdir()), [])

    def test_archive_expansion_is_bounded_before_installation(self) -> None:
        import zipfile
        import io

        payload = make_zip({"actionlint.exe": b"oversized expansion"})
        with mock.patch.object(self.installer, "MAX_EXTRACTED_BYTES", 1):
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                with self.assertRaisesRegex(
                    self.installer.InstallerError, "archive size limit"
                ):
                    self.installer._validate_zip_members(archive.infolist())
        with mock.patch.object(self.installer, "MAX_ARCHIVE_MEMBERS", 0):
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                with self.assertRaisesRegex(
                    self.installer.InstallerError, "archive member limit"
                ):
                    self.installer._validate_zip_members(archive.infolist())

    def test_local_selection_and_native_platform_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "chosen"
            for overrides, diagnostic in [
                ({"tool_names": None}, "requires.*--tool"),
                ({"tool_names": []}, "requires.*--tool"),
                ({"platform_name": "windows-x64"}, "native platform"),
            ]:
                with (
                    self.subTest(overrides=overrides),
                    self.assertRaisesRegex(self.installer.InstallerError, diagnostic),
                ):
                    self.install(root, dry_run=True, **overrides)

    def test_windows_variants_select_exe_members_and_shared_probes(self) -> None:
        expected = {
            "shfmt": "binary",
            "actionlint": "zip",
            "gitleaks": "zip",
            "shellcheck": "zip",
        }
        for name, kind in expected.items():
            with self.subTest(tool=name), tempfile.TemporaryDirectory() as temporary:
                record = self.installer.platform_record(
                    self.registry["external"][name], "windows-x64"
                )
                self.assertEqual(record["artifactType"], kind)
                self.assertEqual(record["install"]["target"], f"bin/{name}.exe")
                payload = b"native test member"
                artifact = (
                    payload if kind == "binary" else make_zip({f"{name}.exe": payload})
                )
                self.registry["external"][name]["variants"]["windows-x64"]["sha256"] = (
                    hashlib.sha256(artifact).hexdigest()
                )
                calls = []

                def probe(command, **options):
                    calls.append(command)
                    self.assertEqual(Path(command[0]).suffix, ".exe")
                    self.assertEqual(Path(command[0]).read_bytes(), payload)
                    return subprocess.CompletedProcess(
                        command, 0, record["probe"]["expectedLine"] + "\n", ""
                    )

                with mock.patch.object(
                    self.installer, "native_platform", return_value="windows-x64"
                ):
                    self.installer.install_tools(
                        self.registry,
                        local=True,
                        platform_name="windows-x64",
                        install_root=Path(temporary) / "chosen",
                        tool_names=[name],
                        run_command=probe,
                        open_url=lambda request, **unused: FakeResponse(
                            artifact, request.full_url
                        ),
                    )
                self.assertEqual(len(calls), 1)

    def test_old_schema2_without_variants_and_incompatible_selection(self) -> None:
        for record in self.registry["external"].values():
            record.pop("variants", None)
        self.installer.validate_registry(self.registry)
        self.assertEqual(
            self.installer._selected_tools(self.registry, "windows-x64", None),
            ["PSScriptAnalyzer"],
        )
        with self.assertRaisesRegex(self.installer.InstallerError, "unavailable"):
            self.installer._selected_tools(self.registry, "windows-x64", ["shfmt"])

    def test_declaration_checker_validates_variants_and_runtime_probes_remain_shared(
        self,
    ) -> None:
        checker = load_script_module(
            INSTALLER_PATH.with_name("check-versions.py"), "local_versions_test"
        )
        self.assertEqual(
            checker.validate_registry(INSTALLER_PATH.parent, self.registry), []
        )
        commands = checker.external_commands(self.registry["external"])
        for name in ("shfmt", "actionlint", "shellcheck", "gitleaks"):
            for platform in ("linux-x64", "windows-x64"):
                record = self.installer.platform_record(
                    self.registry["external"][name], platform
                )
                self.assertEqual(commands[name][1:], record["probe"]["arguments"])
                self.assertEqual(
                    record["probe"], self.registry["external"][name]["probe"]
                )
        self.registry["external"]["shfmt"]["variants"]["windows-x64"]["url"] = (
            "http://unsafe.test"
        )
        errors = checker.validate_registry(INSTALLER_PATH.parent, self.registry)
        self.assertEqual(len(errors), 1)
        self.assertIn("unsafe URL", errors[0])

    def test_variant_contract_rejects_unknown_platform_key_probe_and_duplicate_target(
        self,
    ) -> None:
        for change, diagnostic in [
            (
                lambda record: record["variants"].__setitem__("macos-x64", {}),
                "variant platform",
            ),
            (
                lambda record: record["variants"]["windows-x64"].__setitem__(
                    "url", "http://unsafe.test"
                ),
                "unsafe URL",
            ),
            (
                lambda record: record["variants"]["windows-x64"].__setitem__(
                    "probe", {}
                ),
                "unexpected key probe",
            ),
            (
                lambda record: record["variants"]["windows-x64"]["install"].__setitem__(
                    "target", "bin/actionlint.exe"
                ),
                "duplicate install target",
            ),
        ]:
            registry = copy.deepcopy(self.registry)
            change(registry["external"]["shfmt"])
            with (
                self.subTest(diagnostic=diagnostic),
                self.assertRaisesRegex(self.installer.InstallerError, diagnostic),
            ):
                self.installer.validate_registry(registry)

    def test_registry_rejects_target_ancestors_in_both_orders_and_case(self) -> None:
        for first, second in (
            ("bin/parent", "bin/parent/child"),
            ("bin/parent/child", "bin/parent"),
            ("BIN/Parent", "bin/PARENT/child"),
            ("BIN/Parent/child", "bin/PARENT"),
        ):
            registry = copy.deepcopy(self.registry)
            for tool, target in (("shfmt", first), ("actionlint", second)):
                registry["external"][tool]["variants"]["windows-x64"]["install"][
                    "target"
                ] = target
            with self.subTest(first=first, second=second):
                with self.assertRaisesRegex(
                    self.installer.InstallerError, "install target"
                ):
                    self.installer.validate_registry(registry)
        registry = copy.deepcopy(self.registry)
        registry["external"]["shfmt"]["variants"]["windows-x64"]["install"][
            "target"
        ] = "bin/sibling-one"
        registry["external"]["actionlint"]["variants"]["windows-x64"]["install"][
            "target"
        ] = "bin/sibling-two"
        registry["external"]["shfmt"]["install"]["target"] = "bin/sibling-two/child"
        self.installer.validate_registry(registry)

    def test_local_dry_run_rejects_target_ancestors_before_side_effects(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["external"]["shfmt"]["variants"]["windows-x64"]["install"][
            "target"
        ] = "bin/actionlint.exe/child"
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            opener, runner = mock.Mock(), mock.Mock()
            with mock.patch.object(
                self.installer, "native_platform", return_value="windows-x64"
            ):
                with self.assertRaisesRegex(
                    self.installer.InstallerError, "install target"
                ):
                    self.installer.install_tools(
                        registry,
                        platform_name="windows-x64",
                        install_root=parent / "chosen",
                        local=True,
                        tool_names=["shfmt"],
                        dry_run=True,
                        open_url=opener,
                        run_command=runner,
                    )
            self.assertEqual(list(parent.iterdir()), [])
            opener.assert_not_called()
            runner.assert_not_called()

    def test_windows_zip_rejects_unexpected_executable_and_unsafe_layouts(self) -> None:
        import stat
        import zipfile

        link = zipfile.ZipInfo("link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archives = [
            make_zip({"actionlint.exe": b"exe", "other.exe": b"bad"}),
            make_zip({"actionlint.exe": b"exe", "unexpected.txt": b"bad"}),
            make_zip({"actionlint.exe": b"exe", "../escape": b"bad"}),
            make_zip_members([("actionlint.exe", b"exe"), ("ACTIONLINT.exe", b"bad")]),
            make_zip_members([("actionlint.exe", b"exe"), (link, b"target")]),
        ]
        for artifact in archives:
            with tempfile.TemporaryDirectory() as temporary:
                parent = Path(temporary)
                self.registry["external"]["actionlint"]["variants"]["windows-x64"][
                    "sha256"
                ] = hashlib.sha256(artifact).hexdigest()
                with mock.patch.object(
                    self.installer, "native_platform", return_value="windows-x64"
                ):
                    with self.assertRaisesRegex(
                        self.installer.InstallerError, "unsafe archive entry"
                    ):
                        self.installer.install_tools(
                            self.registry,
                            local=True,
                            platform_name="windows-x64",
                            install_root=parent / "chosen",
                            tool_names=["actionlint"],
                            open_url=lambda request, **unused: FakeResponse(
                                artifact, request.full_url
                            ),
                            run_command=mock.Mock(),
                        )
                self.assertEqual(list(parent.iterdir()), [])

    def test_local_checksum_probe_and_publication_failure_cleanup(self) -> None:
        for overrides in [
            {
                "open_url": lambda request, **unused: FakeResponse(
                    b"corrupt", request.full_url
                )
            },
            {
                "run_command": lambda command, **unused: subprocess.CompletedProcess(
                    command, 1, "", "failed"
                )
            },
            {
                "run_command": mock.Mock(
                    side_effect=subprocess.TimeoutExpired(["shfmt"], 15)
                )
            },
        ]:
            with tempfile.TemporaryDirectory() as temporary:
                parent = Path(temporary)
                with self.assertRaises(self.installer.InstallerError):
                    self.install(parent / "chosen", **overrides)
                self.assertEqual(list(parent.iterdir()), [])
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            with mock.patch.object(
                self.installer, "_publish", side_effect=OSError("publication denied")
            ):
                with self.assertRaises(OSError):
                    self.install(parent / "chosen")
            self.assertEqual(list(parent.iterdir()), [])

    def test_atomic_publication_never_overwrites_raced_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            staging, existing = parent / "staging", parent / "existing"
            staging.mkdir()
            (staging / "proof").write_text("preserve")
            existing.mkdir()
            with self.assertRaises(OSError):
                self.installer._publish(staging, existing)
            self.assertTrue((staging / "proof").exists())
            self.assertEqual(list(existing.iterdir()), [])

    def test_ci_publication_failure_cleans_new_parents_and_preserves_existing_parent(
        self,
    ) -> None:
        for existing in (False, True):
            with (
                self.subTest(existing=existing),
                tempfile.TemporaryDirectory() as temporary,
            ):
                parent = Path(temporary)
                nested = parent / "nested"
                if existing:
                    nested.mkdir()
                    (nested / "preserve").write_text("existing data")
                with mock.patch.object(
                    self.installer,
                    "_publish",
                    side_effect=OSError("publication failed"),
                ):
                    with self.assertRaises(OSError):
                        self.install(nested / "chosen", local=False, runner_temp=parent)
                self.assertEqual(
                    [path.name for path in parent.iterdir()],
                    ["nested"] if existing else [],
                )
                if existing:
                    self.assertEqual((nested / "preserve").read_text(), "existing data")

    def test_ci_raced_parent_is_not_owned_by_failed_installation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            nested = parent / "nested"
            publish = self.installer._publish
            raced_identity = []

            def create_concurrently(staging, destination):
                destination.mkdir()
                (destination / "competitor").write_bytes(b"other invocation")
                raced_identity.append(destination.stat())
                publish(staging, destination)

            with (
                mock.patch.object(self.installer, "_publish", create_concurrently),
                self.assertRaises(OSError),
            ):
                self.install(nested / "chosen", local=False, runner_temp=parent)
            self.assertTrue(nested.is_dir())
            self.assertFalse((nested / "chosen").exists())
            self.assertEqual((nested / "competitor").read_bytes(), b"other invocation")
            self.assertEqual(
                (nested.stat().st_dev, nested.stat().st_ino),
                (raced_identity[0].st_dev, raced_identity[0].st_ino),
            )
            self.assertFalse((nested / "chosen").exists())
            self.assertEqual(list(parent.iterdir()), [nested])

    def test_ci_post_mkdir_replacement_is_never_recorded_owned(self) -> None:
        for with_bytes in (False, True):
            with (
                self.subTest(with_bytes=with_bytes),
                tempfile.TemporaryDirectory() as temporary,
            ):
                parent = Path(temporary)
                nested, saved = parent / "nested", parent / "exposed-original"
                mkdir = Path.mkdir
                competitor_identity = []

                def replace_after_success(path, *args, **kwargs):
                    result = mkdir(path, *args, **kwargs)
                    if path == nested:
                        nested.rename(saved)
                        mkdir(nested)
                        competitor_identity.append(nested.stat())
                        if with_bytes:
                            (nested / "competitor").write_bytes(b"preserve bytes")
                    return result

                def fail_publication(*unused):
                    if not competitor_identity:
                        # With private preparation there is no public mkdir
                        # window; compete immediately before atomic publication.
                        mkdir(nested)
                        competitor_identity.append(nested.stat())
                        if with_bytes:
                            (nested / "competitor").write_bytes(b"preserve bytes")
                    raise OSError("original publication failed")

                with (
                    mock.patch.object(Path, "mkdir", replace_after_success),
                    mock.patch.object(self.installer, "_publish", fail_publication),
                    self.assertRaisesRegex(OSError, "original publication failed"),
                ):
                    self.install(nested / "chosen", local=False, runner_temp=parent)
                self.assertTrue(nested.is_dir())
                self.assertEqual(
                    (nested.stat().st_dev, nested.stat().st_ino),
                    (competitor_identity[0].st_dev, competitor_identity[0].st_ino),
                )
                if with_bytes:
                    self.assertEqual(
                        (nested / "competitor").read_bytes(), b"preserve bytes"
                    )
                self.assertFalse(
                    saved.exists(), "installer exposed a public mkdir name"
                )
                self.assertFalse((nested / "chosen").exists())

    def test_ci_rollback_preserves_replaced_and_nonempty_owned_parents(self) -> None:
        for change in ("replacement", "nonempty"):
            with (
                self.subTest(change=change),
                tempfile.TemporaryDirectory() as temporary,
            ):
                parent = Path(temporary)
                nested = parent / "nested"
                saved = parent / "saved-original"
                nested.mkdir()

                def fail_publication(*unused):
                    if change == "replacement":
                        nested.rename(saved)
                        nested.mkdir()
                    else:
                        (nested / "other-owner").write_text("preserve")
                    raise OSError("original publication failed")

                with (
                    mock.patch.object(self.installer, "_publish", fail_publication),
                    self.assertRaisesRegex(OSError, "original publication failed"),
                ):
                    self.install(nested / "chosen", local=False, runner_temp=parent)
                self.assertTrue(nested.is_dir())
                if change == "replacement":
                    self.assertTrue(saved.is_dir())
                    self.assertEqual(list(nested.iterdir()), [])
                else:
                    self.assertEqual((nested / "other-owner").read_text(), "preserve")
                self.assertFalse((nested / "chosen").exists())

    def test_ci_failed_multilevel_publication_leaves_no_public_parents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            lower = parent / "upper/lower"
            public_before_publication = []

            def fail_publication(*unused):
                public_before_publication.extend(
                    path.name
                    for path in parent.iterdir()
                    if not path.name.startswith(".external-tools-")
                )
                raise OSError("original publication failed")

            with (
                mock.patch.object(self.installer, "_publish", fail_publication),
                self.assertRaisesRegex(OSError, "original publication failed"),
            ):
                self.install(lower / "chosen", local=False, runner_temp=parent)
            self.assertEqual(public_before_publication, [])
            self.assertEqual(list(parent.iterdir()), [])

    def test_ci_rollback_does_not_remove_a_replacement_link_or_junction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            nested, saved, outside = (
                parent / "nested",
                parent / "saved",
                parent / "outside",
            )
            outside.mkdir()
            publish = self.installer._publish

            def fail_publication(staging, destination):
                if nested.exists():
                    nested.rename(saved)
                if sys.platform == "win32":
                    environment = os.environ.copy()
                    environment["QUALITY_TEST_LINK"] = str(nested)
                    environment["QUALITY_TEST_TARGET"] = str(outside)
                    environment["POWERSHELL_TELEMETRY_OPTOUT"] = "1"
                    environment["PSModuleAnalysisCachePath"] = str(
                        parent / "module-cache"
                    )
                    result = subprocess.run(
                        [
                            "pwsh",
                            "-NoProfile",
                            "-NonInteractive",
                            "-Command",
                            "New-Item -ItemType Junction -Path $env:QUALITY_TEST_LINK -Target $env:QUALITY_TEST_TARGET | Out-Null",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        env=environment,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    nested.symlink_to(outside, target_is_directory=True)
                publish(staging, destination)

            with (
                mock.patch.object(self.installer, "_publish", fail_publication),
                self.assertRaises(OSError),
            ):
                self.install(nested / "chosen", local=False, runner_temp=parent)
            self.assertTrue(self.installer._is_link(nested))
            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse(
                saved.exists(), "installer created a public parent before publication"
            )

    def test_private_subtree_publication_preserves_exact_root_layout_and_modes(
        self,
    ) -> None:
        import stat

        for local, relative in (
            (True, "chosen"),
            (False, "chosen"),
            (False, "one/chosen"),
            (False, "one/two/three/chosen"),
            (False, "existing/one/two/chosen"),
        ):
            with (
                self.subTest(local=local, relative=relative),
                tempfile.TemporaryDirectory() as temporary,
            ):
                parent = Path(temporary)
                reference = parent / "mode-reference"
                reference.mkdir()
                default_mode = stat.S_IMODE(reference.stat().st_mode)
                reference.rmdir()
                existing = parent / "existing"
                existing.mkdir()
                (existing / "preserve").write_bytes(b"existing data")
                root = parent / relative
                self.install(root, local=local, runner_temp=None if local else parent)
                self.assertEqual(
                    (root / "bin/shfmt").read_bytes(), b"fake pinned executable"
                )
                self.assertEqual((existing / "preserve").read_bytes(), b"existing data")
                self.assertEqual(
                    {
                        path.relative_to(parent).as_posix()
                        for path in parent.rglob("*")
                        if path.is_file()
                    },
                    {"existing/preserve", f"{relative}/bin/shfmt"},
                )
                self.assertFalse(
                    any(
                        path.name.startswith(".external-tools-")
                        for path in parent.iterdir()
                    )
                )
                if os.name != "nt":
                    self.assertEqual(
                        stat.S_IMODE((root / "bin/shfmt").stat().st_mode), 0o755
                    )
                    for path in (root, *root.parents):
                        if path == parent:
                            break
                        self.assertEqual(
                            stat.S_IMODE(path.stat().st_mode), default_mode
                        )

    def test_tar_limits_reject_before_traversing_oversized_payload(self) -> None:
        for kind in ("tar.gz", "tar.xz"):
            for limit in ("size", "members"):
                with self.subTest(kind=kind, limit=limit):
                    entries = [("release/actionlint", b"x" * (4 * 1024 * 1024), None)]
                    if limit == "members":
                        entries.insert(0, ("README", b"tiny", None))
                        entries.extend(
                            (f"extra-{index}", b"", None) for index in range(20)
                        )
                    artifact = make_tar(kind, entries)
                    record = self.registry["external"]["actionlint"]
                    record["artifactType"] = kind
                    record["install"] = {
                        "kind": "executable",
                        "target": "bin/actionlint",
                        **(
                            {"memberBasename": "actionlint"}
                            if kind == "tar.gz"
                            else {"member": "release/actionlint"}
                        ),
                    }
                    record["sha256"] = hashlib.sha256(artifact).hexdigest()
                    positions = []
                    tar_open = self.installer.tarfile.open

                    def observe_tar(*args, **kwargs):
                        archive = tar_open(*args, **kwargs)
                        stream = archive.fileobj
                        close = stream.close

                        def record_position():
                            if not stream.closed:
                                positions.append(stream.tell())
                            close()

                        stream.close = record_position
                        return archive

                    with (
                        tempfile.TemporaryDirectory() as temporary,
                        mock.patch.object(self.installer.tarfile, "open", observe_tar),
                        mock.patch.object(
                            self.installer,
                            "MAX_EXTRACTED_BYTES",
                            1024 if limit == "size" else 8 * 1024 * 1024,
                        ),
                        mock.patch.object(
                            self.installer,
                            "MAX_ARCHIVE_MEMBERS",
                            1 if limit == "members" else 100,
                        ),
                        self.assertRaisesRegex(
                            self.installer.InstallerError,
                            f"archive {'size' if limit == 'size' else 'member'} limit",
                        ),
                    ):
                        root = Path(temporary)
                        self.install(
                            root / "chosen",
                            tool_names=["actionlint"],
                            open_url=lambda request, **unused: FakeResponse(
                                artifact, request.full_url
                            ),
                        )
                    self.assertEqual(len(positions), 1)
                    self.assertLess(positions[0], 4096)

    def test_download_has_total_deadline_and_size_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            record = self.registry["external"]["shfmt"]

            def opener(request, **unused):
                return FakeResponse(b"payload", request.full_url)

            with mock.patch.object(
                self.installer.time, "monotonic", side_effect=[0, 0, 61]
            ):
                with self.assertRaisesRegex(
                    self.installer.InstallerError, "download.*timed out"
                ):
                    self.installer._download(
                        "shfmt", record, Path(temporary) / "deadline", opener
                    )
            with mock.patch.object(self.installer, "MAX_DOWNLOAD_BYTES", 1):
                with self.assertRaisesRegex(
                    self.installer.InstallerError, "download.*size limit"
                ):
                    self.installer._download(
                        "shfmt", record, Path(temporary) / "size", opener
                    )

    def test_default_network_download_uses_contained_deadline_and_reports_failure(
        self,
    ) -> None:
        record = self.registry["external"]["shfmt"]
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "artifact"
            for outcome, diagnostic in [
                (subprocess.TimeoutExpired(["download"], 60), "timed out"),
                (
                    subprocess.CompletedProcess(["download"], 1, "", "network failed"),
                    "network failed",
                ),
            ]:
                runner = (
                    mock.Mock(side_effect=outcome)
                    if isinstance(outcome, Exception)
                    else mock.Mock(return_value=outcome)
                )
                with mock.patch.object(self.installer, "_bounded_run", runner):
                    with self.assertRaisesRegex(
                        self.installer.InstallerError, f"download failed.*{diagnostic}"
                    ):
                        self.installer._bounded_download("shfmt", record, destination)
                self.assertEqual(runner.call_args.kwargs["timeout"], 60)
                self.assertEqual(runner.call_args.kwargs["cwd"], destination.parent)
                self.assertEqual(runner.call_args.args[0][0], sys.executable)
                self.assertFalse(destination.exists())

    def test_blocked_network_worker_deadline_kills_descendants_and_cleans_install(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            started_marker = parent / "download-child-started"
            survived_marker = parent / "download-child-survived"
            release_marker = parent / "download-child-release"
            timeout = self.installer.DOWNLOAD_TIMEOUT_SECONDS
            child_code = (
                "import time,pathlib; "
                f"release=pathlib.Path({str(release_marker)!r}); "
                f"deadline=time.monotonic()+{timeout + 30}\n"
                "while not release.exists() and time.monotonic()<deadline: time.sleep(0.01)\n"
                f"pathlib.Path({str(survived_marker)!r}).write_text('bad')"
            )
            fixture = f"""import ctypes, subprocess, time
from pathlib import Path
{inspect.getsource(_process_creation)}
class BlockedResponse:
    def __enter__(self): return self
    def __exit__(self, *unused): pass
    def geturl(self): return json.loads(sys.argv[3])['url']
    def read(self, size):
        child = subprocess.Popen([sys.executable, '-c', {child_code!r}])
        handle = int(child._handle) if sys.platform == 'win32' else None
        identity = _process_creation(child.pid, handle)
        pathlib.Path({str(started_marker)!r}).write_text(json.dumps({{'pid': child.pid, 'creation': identity}}), encoding='utf-8')
        time.sleep({timeout + 30})
module._safe_urlopen = lambda *args, **kwargs: BlockedResponse()
"""
            worker = self.installer.DOWNLOAD_WORKER_SCRIPT.replace(
                "try:\n", fixture + "try:\n", 1
            )
            platform = "windows-x64" if sys.platform == "win32" else "linux-x64"
            start = time.monotonic()
            contained = False
            try:
                with mock.patch.object(
                    self.installer, "DOWNLOAD_WORKER_SCRIPT", worker
                ):
                    with self.assertRaisesRegex(
                        self.installer.InstallerError, "download failed: timed out"
                    ):
                        self.installer.install_tools(
                            self.registry,
                            local=True,
                            platform_name=platform,
                            install_root=parent / "chosen",
                            tool_names=["shfmt"],
                        )
                self.assertLess(time.monotonic() - start, timeout + 2)
                self.assertTrue(
                    started_marker.exists(),
                    "worker must enter read and create a descendant before timeout",
                )
                self.assertEqual(list(parent.iterdir()), [started_marker])
                release_marker.write_text("parent completed timeout")
                time.sleep(2)
                self.assertFalse(survived_marker.exists())
                contained = True
            finally:
                if not contained and started_marker.exists():
                    attestation = json.loads(started_marker.read_text(encoding="utf-8"))
                    _stop_attested_child(attestation["pid"], attestation["creation"])

    def test_attested_cleanup_rejects_changed_identity(self) -> None:
        child = subprocess.Popen(
            [sys.executable, "-B", "-c", "import time; time.sleep(30)"]
        )
        try:
            with self.assertRaisesRegex(ValueError, "identity changed"):
                _stop_attested_child(child.pid, -1)
            self.assertIsNone(
                child.poll(), "identity rejection must not terminate the process"
            )
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)

    def test_attested_cleanup_terminates_only_the_owned_child(self) -> None:
        child = subprocess.Popen(
            [sys.executable, "-B", "-c", "import time; time.sleep(30)"]
        )
        try:
            handle = int(child._handle) if sys.platform == "win32" else None
            creation = _process_creation(child.pid, handle)
            _stop_attested_child(child.pid, creation)
            self.assertIsNotNone(child.wait(timeout=5))
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)

    def test_default_probe_deadline_terminates_child_tree_and_cleans_staging(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            child_marker = parent / "child-survived"
            child_code = f"import time,pathlib; time.sleep(2); pathlib.Path({str(child_marker)!r}).write_text('bad')"
            parent_code = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child_code!r}]); time.sleep(30)"
            start = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                self.installer._bounded_run(
                    [sys.executable, "-c", parent_code],
                    timeout=0.5,
                    capture_output=True,
                    text=True,
                    check=False,
                    shell=False,
                    cwd=parent,
                    env=None,
                )
            self.assertLess(time.monotonic() - start, 2)
            time.sleep(2)
            self.assertFalse(child_marker.exists())

    def test_cli_local_dry_run_without_runner_temp_and_standard_options(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            environment = os.environ.copy()
            environment.pop("RUNNER_TEMP", None)
            platform = "windows-x64" if sys.platform == "win32" else "linux-x64"
            root = Path(temporary) / "chosen"
            arguments = [sys.executable, "-B", str(INSTALLER_PATH)]
            result = subprocess.run(
                arguments
                + [
                    "--local",
                    "--dry-run",
                    "-v",
                    "--platform",
                    platform,
                    "--install-root",
                    str(root),
                    "--tool",
                    "shfmt",
                ],
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("dry-run", result.stdout)
            self.assertFalse(root.exists())
            for flag in ("--help", "--version"):
                result = subprocess.run(
                    arguments + [flag],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            missing = subprocess.run(
                arguments + ["--local", "--platform", platform, "--tool", "shfmt"],
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(missing.returncode, 2)

    def test_user_cli_dry_run_without_bytecode_flags_preserves_fixture_exactly(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality = root / "tools/quality"
            quality.mkdir(parents=True)
            for source in (INSTALLER_PATH, INSTALLER_PATH.with_name("versions.json")):
                shutil.copyfile(source, quality / source.name)
            shutil.copyfile(
                INSTALLER_PATH.parents[1] / "process_runner.py",
                root / "tools/process_runner.py",
            )

            def snapshot():
                return {
                    path.relative_to(root).as_posix(): hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                    if path.is_file()
                    else None
                    for path in root.rglob("*")
                }

            before = snapshot()
            environment = os.environ.copy()
            environment.pop("RUNNER_TEMP", None)
            environment.pop("PYTHONDONTWRITEBYTECODE", None)
            platform = "windows-x64" if sys.platform == "win32" else "linux-x64"
            result = subprocess.run(
                [
                    sys.executable,
                    str(quality / INSTALLER_PATH.name),
                    "--local",
                    "--dry-run",
                    "--platform",
                    platform,
                    "--install-root",
                    "tools/quality/external",
                    "--tool",
                    "shfmt",
                ],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(snapshot(), before)
            self.assertEqual(list(root.rglob("__pycache__")), [])


if __name__ == "__main__":
    unittest.main()
