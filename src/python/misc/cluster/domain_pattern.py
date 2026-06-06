#!/usr/bin/env python3
"""Parse domain suffix keywords for cluster host discovery (setup step 7)."""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_ZONE_SUFFIXES: tuple[str, ...] = (
    "lan",
    "local",
    "internal",
    "home",
    "home.arpa",
    "",
)

_GLOB_CHARS = frozenset("*?")


def contains_glob(domain: str) -> bool:
    return any(char in domain for char in _GLOB_CHARS)


def load_zone_suffixes(path: Path | None) -> tuple[str, ...]:
    if path is None or not path.is_file():
        return DEFAULT_ZONE_SUFFIXES
    items: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            items.append(line)
    return tuple(items) if items else DEFAULT_ZONE_SUFFIXES


def expand_domain_suffix(
    domain: str,
    zone_suffixes: tuple[str, ...] = DEFAULT_ZONE_SUFFIXES,
) -> list[str]:
    """
    Expand a domain suffix keyword into concrete DNS suffix strings.

    Literal:
      cluster.home.arpa  -> [cluster.home.arpa]

    Trailing wildcard (try common zone labels under a base name):
      oldtimers.*        -> [oldtimers.lan, oldtimers.local, oldtimers, ...]

    Leading wildcard (fixed suffix after the short hostname):
      *.oldtimers.lan    -> [oldtimers.lan]
    """
    domain = domain.strip().lstrip(".")
    if not domain:
        return []

    if not contains_glob(domain):
        return [domain]

    if domain.endswith(".*"):
        base = domain[:-2].rstrip(".")
        if not base:
            return list(zone_suffixes)
        expanded: list[str] = []
        for zone in zone_suffixes:
            expanded.append(f"{base}.{zone}" if zone else base)
        return expanded

    if domain.startswith("*."):
        return [domain[2:].lstrip(".")]

    return [domain]


def fqdn_candidates(
    short: str,
    domain: str,
    *,
    zone_suffixes: tuple[str, ...] = DEFAULT_ZONE_SUFFIXES,
) -> list[str]:
    """Build ordered unique FQDN candidates for DNS lookup."""
    short = short.strip()
    if not short:
        return []
    if "." in short:
        return [short]

    seen: set[str] = set()
    candidates: list[str] = []
    for suffix in expand_domain_suffix(domain, zone_suffixes):
        fqdn = f"{short}.{suffix}" if suffix else short
        if fqdn not in seen:
            seen.add(fqdn)
            candidates.append(fqdn)
    return candidates


def glob_domain_to_regex(domain: str) -> re.Pattern[str] | None:
    """When the domain keyword is a glob, return a regex that matches full FQDNs."""
    domain = domain.strip().lstrip(".")
    if not contains_glob(domain):
        return None

    if domain.endswith(".*"):
        base = re.escape(domain[:-2].rstrip("."))
        return re.compile(rf"^[^.]+\.{base}(\.[^.]+)*$")

    if domain.startswith("*."):
        suffix = re.escape(domain[2:].lstrip("."))
        return re.compile(rf"^[^.]+\.{suffix}$")

    escaped = re.escape(domain).replace(r"\*", r"[^.]+").replace(r"\?", r"[^.]")
    return re.compile(rf"^[^.]+\.{escaped}$")
