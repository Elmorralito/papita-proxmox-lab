"""Default data files for papita Python tooling on PVE nodes."""

from __future__ import annotations

from pathlib import Path

DATAFILES_DIR = Path(__file__).resolve().parent
DEFAULT_HOSTS_LIST = DATAFILES_DIR / "default.hosts.list"
DEFAULT_HOSTS_REGEX = DATAFILES_DIR / "default.hosts.regex"
DEFAULT_DOMAIN_SUFFIXES_LIST = DATAFILES_DIR / "default.domain.suffixes.list"

__all__ = [
    "DATAFILES_DIR",
    "DEFAULT_DOMAIN_SUFFIXES_LIST",
    "DEFAULT_HOSTS_LIST",
    "DEFAULT_HOSTS_REGEX",
]
