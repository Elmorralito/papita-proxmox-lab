#!/usr/bin/env python3
"""Discover Proxmox cluster peer hostnames via DNS and emit /etc/hosts lines.

Used during PVE node setup (step 7) before ``pvecm`` cluster join. Reads short
hostnames from a candidates file, expands them into FQDNs using configurable
domain suffix keywords (see ``domain_pattern``), resolves the first matching
IPv4 address for each candidate, filters results by domain glob and a caller-
supplied regex, and prints tab-separated ``/etc/hosts`` entries to stdout.

Each emitted line has the form ``IP\\tFQDN\\tshortname``. Warnings for
unresolvable names go to stderr. When no hosts match, the process exits with
code 2.

Public entry point: ``main()`` (also invoked when run as ``__main__``).
"""

from __future__ import annotations

import argparse
import re
import socket
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .domain_pattern import (
        fqdn_candidates,
        glob_domain_to_regex,
        load_zone_suffixes,
    )
else:
    try:
        from .domain_pattern import (
            fqdn_candidates,
            glob_domain_to_regex,
            load_zone_suffixes,
        )
    except ImportError:
        from domain_pattern import (
            fqdn_candidates,
            glob_domain_to_regex,
            load_zone_suffixes,
        )


def resolve_ipv4(name: str) -> str | None:
    """Resolve the first IPv4 address for a hostname or FQDN.

    Args:
        name: Hostname or fully qualified domain name to look up.

    Returns:
        Dotted-quad IPv4 address string, or ``None`` when DNS lookup fails or no
        IPv4 record exists for ``name``.
    """
    try:
        infos = socket.getaddrinfo(name, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
        return str(infos[0][4][0])
    except socket.gaierror:
        return None


def load_candidates(path: Path) -> list[str]:
    """Load short hostnames from a newline-delimited candidates file.

    Blank lines and inline ``#`` comments are ignored. Returns an empty list when
    ``path`` does not exist or is not a regular file.

    Args:
        path: Filesystem path to the candidates list (e.g.
            ``datafiles/default.hosts.list``).

    Returns:
        Ordered list of non-empty hostname strings with comments stripped.
    """
    if not path.is_file():
        return []
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def emit_host(ip: str, fqdn: str, seen: set[str]) -> bool:
    """Print one ``/etc/hosts`` line if the IP/FQDN pair has not been emitted yet.

    Output format: ``{ip}\\t{fqdn}\\t{short}`` where ``short`` is the label before
    the first dot in ``fqdn``. Duplicate pairs are suppressed using ``seen``.

    Args:
        ip: Resolved IPv4 address.
        fqdn: Fully qualified domain name that resolved to ``ip``.
        seen: Mutable set of already-printed ``"{ip}\\t{fqdn}"`` keys; updated on
            success.

    Returns:
        ``True`` if a new line was printed; ``False`` if this pair was skipped as
        a duplicate.
    """
    key = f"{ip}\t{fqdn}"
    if key in seen:
        return False
    seen.add(key)
    short = fqdn.split(".", 1)[0]
    print(f"{ip}\t{fqdn}\t{short}")
    return True


def resolve_candidate_fqdn(
    short: str,
    domain: str,
    zone_suffixes: tuple[str, ...],
    resolver: Callable[[str], str | None],
) -> tuple[str | None, str | None]:
    """Try FQDN variants for a short name until one resolves via ``resolver``.

    Candidate FQDNs are built in order by ``fqdn_candidates`` from ``short``,
    ``domain``, and ``zone_suffixes``. The first name for which ``resolver``
    returns a non-empty address wins.

    Args:
        short: Short hostname or existing FQDN (passed through when dotted).
        domain: Domain suffix keyword or literal suffix (e.g. ``oldtimers.*``).
        zone_suffixes: Zone labels used when expanding trailing ``.*`` domains.
        resolver: Callable that maps a hostname/FQDN to an IPv4 string or
            ``None`` (typically ``resolve_ipv4``).

    Returns:
        A ``(fqdn, ip)`` tuple for the first successful lookup, or ``(None, None)``
        when no candidate resolves.
    """
    for fqdn in fqdn_candidates(short, domain, zone_suffixes=zone_suffixes):
        ip = resolver(fqdn)
        if ip:
            return fqdn, ip
    return None, None


def _parse_args() -> argparse.Namespace:
    """Parse CLI flags for cluster host DNS discovery."""
    parser = argparse.ArgumentParser(description="Discover PVE cluster hosts matching a domain regex via DNS")
    parser.add_argument(
        "--domain",
        required=True,
        help="DNS domain suffix (literal cluster.home.arpa or keyword oldtimers.* / *.oldtimers.lan)",
    )
    parser.add_argument("--pattern", required=True, help="Regex applied to each FQDN")
    parser.add_argument("--candidates-file", required=True, help="File of short hostnames")
    parser.add_argument(
        "--zone-suffixes-file",
        default="",
        help="Optional file of zone labels for trailing .* domain keywords",
    )
    parser.add_argument(
        "--include-self",
        action="store_true",
        help="Also try to resolve this machine's hostname/FQDN",
    )
    return parser.parse_args()


def main() -> int:
    """Run host discovery from CLI arguments and print matching ``/etc/hosts`` lines.

    Parses ``--domain``, ``--pattern``, ``--candidates-file``, optional
    ``--zone-suffixes-file``, and ``--include-self``. Each candidate from the
    candidates file is resolved and kept only when its FQDN matches both the
    domain glob (if any) and ``--pattern``. With ``--include-self``, the local
    hostname and FQDN are tried once; the first matching self entry is emitted.

    Side effects:
        Matching host lines are written to stdout. Warnings and errors go to
        stderr. Uses blocking DNS lookups via ``socket.getaddrinfo``.

    Returns:
        ``0`` when at least one host line was printed; ``1`` when ``--pattern``
        is an invalid regex; ``2`` when no hosts resolved after filtering.
    """
    args = _parse_args()

    try:
        pattern = re.compile(args.pattern)
    except re.error as exc:
        print(f"ERROR: invalid regex: {exc}", file=sys.stderr)
        return 1

    domain_regex = glob_domain_to_regex(args.domain)
    zone_suffixes = load_zone_suffixes(Path(args.zone_suffixes_file) if args.zone_suffixes_file else None)

    candidates_path = Path(args.candidates_file)
    seen: set[str] = set()
    found = 0

    def fqdn_matches(fqdn: str) -> bool:
        if domain_regex and not domain_regex.search(fqdn):
            return False
        return bool(pattern.search(fqdn))

    for cand in load_candidates(candidates_path):
        fqdn, ip = resolve_candidate_fqdn(cand, args.domain, zone_suffixes, resolve_ipv4)
        if not fqdn or not ip:
            tried = ", ".join(fqdn_candidates(cand, args.domain, zone_suffixes=zone_suffixes))
            print(f"WARN: no IPv4 address for {cand} (tried: {tried})", file=sys.stderr)
            continue
        if not fqdn_matches(fqdn):
            continue
        if emit_host(ip, fqdn, seen):
            found += 1

    if args.include_self:
        self_names = {socket.gethostname(), socket.getfqdn()}
        for host in sorted(name for name in self_names if name):
            fqdn, ip = resolve_candidate_fqdn(host, args.domain, zone_suffixes, resolve_ipv4)
            if not fqdn or not ip:
                ip = resolve_ipv4(host)
                fqdn = host if ip else None
            if not fqdn or not ip:
                print(
                    f"WARN: no IPv4 address for local host {host}",
                    file=sys.stderr,
                )
                continue
            if not fqdn_matches(fqdn):
                continue
            if emit_host(ip, fqdn, seen):
                found += 1
            break

    if found == 0:
        print(
            "ERROR: no hosts resolved; check domain, regex, and DNS records.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
