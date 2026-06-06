#!/usr/bin/env python3
"""Expand domain suffix keywords into FQDN candidates for cluster host discovery.

Supports literal suffixes (e.g. ``cluster.home.arpa``) and glob-style keywords used
during PVE setup step 7: trailing ``.*`` (try zone labels under a base name),
leading ``*.`` (fixed suffix after the short hostname), and other ``*``/``?``
patterns. Consumed by ``discover_hosts`` to build DNS lookup names and filter
resolved FQDNs.

Public API:
    ``DEFAULT_ZONE_SUFFIXES``, ``contains_glob``, ``load_zone_suffixes``,
    ``expand_domain_suffix``, ``fqdn_candidates``, ``glob_domain_to_regex``.
"""

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
    """Return whether ``domain`` contains glob metacharacters ``*`` or ``?``.

    Args:
        domain: Domain suffix keyword or literal suffix string.

    Returns:
        ``True`` if either glob character appears in ``domain``; otherwise
        ``False``.
    """
    return any(char in domain for char in _GLOB_CHARS)


def load_zone_suffixes(path: Path | None) -> tuple[str, ...]:
    """Load zone labels used when expanding trailing ``.*`` domain keywords.

    Reads a newline-delimited file (comments after ``#`` ignored). When ``path``
    is ``None``, missing, or yields no non-empty lines, returns
    ``DEFAULT_ZONE_SUFFIXES``. An empty line in the file represents trying the
    base name alone (no trailing zone label).

    Args:
        path: Optional path to a zone-suffix list (e.g.
            ``default.domain.suffixes.list``); may be ``None``.

    Returns:
        Tuple of zone label strings, never empty (falls back to defaults).
    """
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
    """Expand a domain suffix keyword into concrete DNS suffix strings.

    Literal suffixes pass through unchanged. Trailing ``.*`` expands the base
    name with each entry in ``zone_suffixes`` (empty zone means the base alone).
    Leading ``*.`` strips the prefix and returns the fixed suffix. Other glob
    patterns are returned as a single literal string after normalization.

    Args:
        domain: Domain keyword or literal suffix; leading dots are stripped.
        zone_suffixes: Zone labels for trailing-``.*`` expansion; defaults to
            ``DEFAULT_ZONE_SUFFIXES``.

    Returns:
        List of suffix strings to append after a short hostname. Empty when
        ``domain`` is blank after normalization.
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
    """Build ordered, deduplicated FQDN candidates for DNS lookup.

    When ``short`` already contains a dot, it is treated as a full FQDN and
    returned as the sole candidate. Otherwise each suffix from
    ``expand_domain_suffix`` is joined as ``{short}.{suffix}`` (or ``short``
    alone when the suffix is empty).

    Args:
        short: Short hostname or existing FQDN.
        domain: Domain suffix keyword passed to ``expand_domain_suffix``.
        zone_suffixes: Zone labels for trailing-``.*`` expansion.

    Returns:
        Unique FQDN strings in expansion order, or an empty list when ``short``
        is blank after stripping.
    """
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
    """Compile a regex that matches full FQDNs allowed by a glob domain keyword.

    Returns ``None`` for literal (non-glob) domains. For trailing ``.*``, matches
    ``short.base`` with optional extra dot-separated labels after ``base``. For
    leading ``*.``, matches ``short.{fixed_suffix}``. Other globs escape literal
    dots and map ``*``/``?`` to ``[^.]+``/``[^.]`` within the suffix portion.

    Args:
        domain: Domain suffix keyword; leading dots are stripped before parsing.

    Returns:
        Compiled pattern anchored to the full FQDN, or ``None`` when ``domain``
        contains no glob characters.
    """
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
