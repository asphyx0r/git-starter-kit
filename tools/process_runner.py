"""Run native processes with deadlines that include inherited output pipes."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from typing import Any


if sys.platform == "win32":

    class _ThreadEntry(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("usage", wintypes.DWORD),
            ("thread_id", wintypes.DWORD),
            ("process_id", wintypes.DWORD),
            ("base_priority", wintypes.LONG),
            ("delta_priority", wintypes.LONG),
            ("flags", wintypes.DWORD),
        ]

    class _WindowsJob:
        """Assign a suspended child before it can create uncontained descendants."""

        def __init__(self) -> None:
            self.api = ctypes.WinDLL("kernel32", use_last_error=True)
            definitions = {
                "CreateJobObjectW": (
                    [ctypes.c_void_p, wintypes.LPCWSTR],
                    wintypes.HANDLE,
                ),
                "AssignProcessToJobObject": (
                    [wintypes.HANDLE, wintypes.HANDLE],
                    wintypes.BOOL,
                ),
                "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
                "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
                "CreateToolhelp32Snapshot": (
                    [wintypes.DWORD, wintypes.DWORD],
                    wintypes.HANDLE,
                ),
                "Thread32First": (
                    [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)],
                    wintypes.BOOL,
                ),
                "Thread32Next": (
                    [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)],
                    wintypes.BOOL,
                ),
                "OpenThread": (
                    [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
                    wintypes.HANDLE,
                ),
                "OpenProcess": (
                    [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
                    wintypes.HANDLE,
                ),
                "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
            }
            for name, (arguments, result) in definitions.items():
                function = getattr(self.api, name)
                function.argtypes = arguments
                function.restype = result
            self.handle = self.api.CreateJobObjectW(None, None)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())

        def assign_and_resume(self, process: subprocess.Popen[Any]) -> None:
            handle = self.api.OpenProcess(0x101, False, process.pid)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not self.api.AssignProcessToJobObject(self.handle, handle):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                self.api.CloseHandle(handle)
            snapshot = self.api.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
            if snapshot == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                entry = _ThreadEntry()
                entry.size = ctypes.sizeof(entry)
                available = self.api.Thread32First(snapshot, ctypes.byref(entry))
                while available:
                    if entry.process_id == process.pid:
                        thread = self.api.OpenThread(2, False, entry.thread_id)
                        if not thread:
                            raise ctypes.WinError(ctypes.get_last_error())
                        try:
                            if self.api.ResumeThread(thread) == 0xFFFFFFFF:
                                raise ctypes.WinError(ctypes.get_last_error())
                        finally:
                            self.api.CloseHandle(thread)
                        return
                    available = self.api.Thread32Next(snapshot, ctypes.byref(entry))
                raise OSError("Unable to find the suspended child thread")
            finally:
                self.api.CloseHandle(snapshot)

        def terminate(self) -> None:
            if not self.api.TerminateJobObject(self.handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())

        def close(self) -> None:
            if not self.api.CloseHandle(self.handle):
                raise ctypes.WinError(ctypes.get_last_error())


class ProcessScope:
    """Own a process tree and reserve part of its deadline for forced cleanup."""

    def __init__(self, command: list[str], *, timeout: float, **options: Any) -> None:
        self.command = command
        self.timeout = timeout
        self.deadline = time.monotonic() + timeout
        self.work_deadline = self.deadline - min(1.0, timeout / 2)
        self.options = options
        self.expired = threading.Event()
        self.failure: OSError | None = None
        if sys.platform == "win32":
            self.job: _WindowsJob | None = None
        else:
            self.job = None
        self.lock = threading.Lock()

    def remaining(self) -> float:
        return max(0, self.deadline - time.monotonic())

    def work_remaining(self) -> float:
        return max(0, self.work_deadline - time.monotonic())

    def __enter__(self) -> ProcessScope:
        if sys.platform == "win32":
            self.job = _WindowsJob()
            self.options["creationflags"] = 4  # CREATE_SUSPENDED
        else:
            self.options["start_new_session"] = True
        try:
            self.process = subprocess.Popen(self.command, **self.options)
            try:
                if self.job is not None:
                    self.job.assign_and_resume(self.process)
            except BaseException:
                self.process.kill()
                try:
                    self.process.wait(timeout=self.timeout)
                finally:
                    for stream in (
                        self.process.stdin,
                        self.process.stdout,
                        self.process.stderr,
                    ):
                        if stream is not None:
                            stream.close()
                raise
        except BaseException:
            if self.job is not None:
                self.job.close()
            raise
        # Native process creation is synchronous, as with subprocess.run(timeout).
        # Start the execution/collection/cleanup budget once containment is ready.
        self.deadline = time.monotonic() + self.timeout
        self.work_deadline = self.deadline - min(1.0, self.timeout / 2)
        self.timer = threading.Timer(self.work_remaining(), self._expire)
        self.timer.daemon = True
        self.timer.start()
        return self

    def terminate(self) -> None:
        with self.lock:
            if self.job is not None:
                self.job.terminate()
            elif sys.platform != "win32":
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # The entire owned group has already exited.

    def _expire(self) -> None:
        self.expired.set()
        try:
            self.terminate()
        except OSError as error:
            self.failure = error

    def __exit__(self, *_exception: Any) -> None:
        self.timer.cancel()
        try:
            self.terminate()
            self.process.wait(timeout=self.remaining())
            self.timer.join(timeout=self.remaining())
            if self.timer.is_alive():
                raise subprocess.TimeoutExpired(self.command, self.timeout)
            if self.failure is not None:
                raise self.failure
        finally:
            if self.job is not None:
                self.job.close()
            # A cleanup timeout must not skip closing the terminated tree's pipes.
            for stream in (
                self.process.stdin,
                self.process.stdout,
                self.process.stderr,
            ):
                if stream is not None and not stream.closed:
                    try:
                        stream.close()
                    except BrokenPipeError:
                        pass  # Termination can leave a buffered request unwritten.


def run(
    command: list[str], *, timeout: float, text: bool = False
) -> subprocess.CompletedProcess[Any]:
    """Capture output while containing descendants and preserving one deadline."""
    with ProcessScope(
        command,
        timeout=timeout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
    ) as scope:
        process = scope.process
        try:
            try:
                stdout, stderr = process.communicate(timeout=scope.work_remaining())
            except subprocess.TimeoutExpired:
                scope.expired.set()
                scope.terminate()
                stdout, stderr = process.communicate(timeout=scope.remaining())
            if scope.expired.is_set():
                raise subprocess.TimeoutExpired(command, timeout, stdout, stderr)
            return subprocess.CompletedProcess(
                command, process.returncode, stdout, stderr
            )
        finally:
            scope.terminate()
            assert process.stdout is not None and process.stderr is not None
            process.stdout.close()
            process.stderr.close()
