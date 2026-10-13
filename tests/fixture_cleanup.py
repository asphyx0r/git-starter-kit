"""Clean owned test directories while preserving persistent deletion errors."""

from __future__ import annotations

from tempfile import TemporaryDirectory
import time


def cleanup_temporary_directory(directory: TemporaryDirectory[str]) -> None:
    # Windows can briefly retain delete-pending directory entries.
    for attempt in range(3):
        try:
            directory.cleanup()
            return
        except OSError as error:
            if getattr(error, "winerror", None) != 145 or attempt == 2:
                raise
            time.sleep(0.01)
