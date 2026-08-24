"""Select PostgreSQL client binaries compatible with the running server."""

from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

VERSION_PATTERN = re.compile(r'(\d+)\.(\d+)')
MISMATCH_PATTERN = re.compile(
    r'server version mismatch|aborting because of server version',
    re.I,
)
PG_BIN_GLOBS = (
    '/usr/lib/postgresql/*/bin/{tool}',
    '/usr/pgsql-*/bin/{tool}',
)


@dataclass(frozen=True)
class PgClient:
    path: str
    version: Tuple[int, int]


def parse_pg_version(text: str) -> Optional[Tuple[int, int]]:
    match = VERSION_PATTERN.search(text or '')
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def parse_server_version_num(value: str) -> Optional[Tuple[int, int]]:
    try:
        num = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if num >= 100000:
        return num // 10000, num % 10000
    return num // 10000, (num // 100) % 100


def is_version_mismatch(stderr: str) -> bool:
    return bool(MISMATCH_PATTERN.search(stderr or ''))


def client_version(binary: str) -> Optional[Tuple[int, int]]:
    try:
        proc = subprocess.run(
            [binary, '--version'],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return parse_pg_version((proc.stdout or '') + (proc.stderr or ''))


def _is_executable(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def discover_clients(tool: str, extra_paths: Sequence[Path] = ()) -> List[PgClient]:
    seen = set()
    found: List[PgClient] = []

    def add(raw: str) -> None:
        candidate = Path(raw)
        if not candidate.is_absolute():
            resolved = shutil.which(raw)
            if not resolved:
                return
            candidate = Path(resolved)
        path = str(candidate)
        if path in seen or not _is_executable(candidate):
            return
        version = client_version(path)
        if version is None:
            return
        seen.add(path)
        found.append(PgClient(path=path, version=version))

    for extra in extra_paths:
        add(str(extra))
    which = shutil.which(tool)
    if which:
        add(which)
    for pattern in PG_BIN_GLOBS:
        for match in sorted(glob.glob(pattern.format(tool=tool))):
            add(match)
    return found


def query_server_version(
    host: str,
    port: str,
    user: str,
    password: str,
    database: str,
    psql_paths: Sequence[str] = (),
) -> Optional[Tuple[int, int]]:
    env = os.environ.copy()
    env['PGPASSWORD'] = password
    binaries = [p for p in psql_paths if p]
    for client in discover_clients('psql'):
        if client.path not in binaries:
            binaries.append(client.path)

    queries = (
        'SHOW server_version_num',
        'SHOW server_version',
    )
    for psql in binaries:
        for sql in queries:
            try:
                proc = subprocess.run(
                    [
                        psql, '-h', host, '-p', str(port), '-U', user, '-d', database,
                        '-tAc', sql,
                    ],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=30,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if proc.returncode != 0:
                continue
            raw = (proc.stdout or '').strip()
            parsed = parse_server_version_num(raw) if 'version_num' in sql else parse_pg_version(raw)
            if parsed:
                return parsed
    return None


def select_postgres_clients(
    tool: str,
    extra_paths: Sequence[Path] = (),
    host: str = '',
    port: str = '',
    user: str = '',
    password: str = '',
    database: str = '',
) -> Tuple[List[PgClient], List[PgClient], Optional[Tuple[int, int]]]:
    found = discover_clients(tool, extra_paths)
    extra_psql = []
    for path in extra_paths:
        sibling = Path(path).parent / 'psql'
        extra_psql.append(str(sibling))
    server = None
    if host:
        server = query_server_version(
            host, port, user, password, database, psql_paths=extra_psql
        )
    if server is None:
        compatible = sorted(found, key=lambda c: c.version, reverse=True)
        return compatible, found, server
    compatible = [c for c in found if c.version[0] >= server[0]]
    compatible.sort(key=lambda c: (c.version[0] - server[0], -c.version[1]))
    return compatible, found, server


def missing_client_error(
    tool: str,
    server_version: Optional[Tuple[int, int]],
    found: List[PgClient],
) -> str:
    found_text = ', '.join(
        f"{c.path} ({c.version[0]}.{c.version[1]})" for c in found
    ) or 'none'
    if server_version:
        major = server_version[0]
        return (
            f"PostgreSQL server is {server_version[0]}.{server_version[1]} but no "
            f"compatible {tool} was found (need {tool} >= {major}). "
            f"Install: sudo apt-get install postgresql-client-{major}\n"
            f"Found: {found_text}"
        )
    return (
        f"No usable {tool} binary was found. "
        f"Install: sudo apt-get install postgresql-client\n"
        f"Found: {found_text}"
    )
