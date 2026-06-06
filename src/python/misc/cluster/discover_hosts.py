#!/usr/bin/env python3
"""Resolve cluster peer hostnames into /etc/hosts lines via DNS (step 7)."""

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
    try:
        infos = socket.getaddrinfo(name, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
        return str(infos[0][4][0])
    except socket.gaierror:
        return None


def load_candidates(path: Path) -> list[str]:
    if not path.is_file():
        return []
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def emit_host(ip: str, fqdn: str, seen: set[str]) -> bool:
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
    for fqdn in fqdn_candidates(short, domain, zone_suffixes=zone_suffixes):
        ip = resolver(fqdn)
        if ip:
            return fqdn, ip
    return None, None


def _parse_args() -> argparse.Namespace:
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
