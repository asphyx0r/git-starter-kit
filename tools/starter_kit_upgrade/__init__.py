"""Cumulative starter-kit upgrade package."""

from .cli import main
from .common import VERSION, UpgradeError

__all__ = ["UpgradeError", "VERSION", "main"]
