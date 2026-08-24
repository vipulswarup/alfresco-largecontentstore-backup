"""Shared PostgreSQL dump for a backup run (stream to gzip)."""

import hashlib
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path

from alfresco_backup.utils.pg_client import (
    PgClient,
    is_version_mismatch,
    missing_client_error,
    select_postgres_clients,
)

from .app_config import AppConfig
from .models import PgDumpInfo, RunContext

logger = logging.getLogger(__name__)


def _embedded_pg_path(config: AppConfig, tool: str) -> Path:
    return config.alf_base_dir / 'postgresql' / 'bin' / tool


def _pg_dump_clients(config: AppConfig):
    extra = [_embedded_pg_path(config, 'pg_dump')]
    return select_postgres_clients(
        'pg_dump',
        extra_paths=extra,
        host=config.pghost,
        port=config.pgport,
        user=config.pguser,
        password=config.pgpassword,
        database=config.pgdatabase,
    )


def create_shared_pg_dump(config: AppConfig, ctx: RunContext) -> PgDumpInfo:
    """Stream pg_dump directly to gzip; compute sha256 and size."""
    started = datetime.now()
    postgres_dir = ctx.postgres_dir()
    postgres_dir.mkdir(parents=True, exist_ok=True)
    out_path = postgres_dir / 'postgres.sql.gz'

    compatible, found, server = _pg_dump_clients(config)
    if not compatible:
        raise RuntimeError(missing_client_error('pg_dump', server, found))

    last_error = None
    for client in compatible:
        if server:
            logger.info(
                "Using pg_dump %s (%s.%s) for server %s.%s",
                client.path,
                client.version[0],
                client.version[1],
                server[0],
                server[1],
            )
        else:
            logger.info(
                "Using pg_dump %s (%s.%s)",
                client.path,
                client.version[0],
                client.version[1],
            )
        try:
            return _run_pg_dump(client, config, ctx, started, out_path)
        except _DumpVersionMismatch as exc:
            last_error = str(exc)
            logger.warning(
                "pg_dump %s is incompatible with the server; trying the next binary",
                client.path,
            )
            if out_path.exists():
                out_path.unlink()
            continue
    if last_error:
        if server:
            last_error = (
                f"{last_error.rstrip()}\n"
                f"Install a matching client: sudo apt-get install postgresql-client-{server[0]}"
            )
        else:
            last_error = (
                f"{last_error.rstrip()}\n"
                "Install a matching client: sudo apt-get install postgresql-client"
            )
    raise RuntimeError(last_error or missing_client_error('pg_dump', server, found))


class _DumpVersionMismatch(RuntimeError):
    pass


def _run_pg_dump(
    client: PgClient,
    config: AppConfig,
    ctx: RunContext,
    started: datetime,
    out_path: Path,
) -> PgDumpInfo:
    env = {'PGPASSWORD': config.pgpassword, 'PATH': os.environ.get('PATH', '')}
    pg_args = [
        client.path,
        '-h', config.pghost,
        '-p', config.pgport,
        '-U', config.pguser,
        '-d', config.pgdatabase,
        '--clean', '--if-exists', '--no-owner', '--no-acl',
    ]

    sha = hashlib.sha256()
    size = 0

    with open(out_path, 'wb') as out_file:
        pg_proc = subprocess.Popen(
            pg_args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        gzip_proc = subprocess.Popen(
            ['gzip', '-c'],
            stdin=pg_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        pg_proc.stdout.close()

        while True:
            chunk = gzip_proc.stdout.read(1024 * 1024)
            if not chunk:
                break
            out_file.write(chunk)
            sha.update(chunk)
            size += len(chunk)

        gzip_stderr = gzip_proc.communicate()[1]
        pg_stderr = pg_proc.communicate()[1]

        if pg_proc.returncode != 0:
            err = pg_stderr.decode('utf-8', errors='replace') if pg_stderr else 'pg_dump failed'
            if is_version_mismatch(err):
                raise _DumpVersionMismatch(err)
            raise RuntimeError(err)
        if gzip_proc.returncode != 0:
            err = gzip_stderr.decode('utf-8', errors='replace') if gzip_stderr else 'gzip failed'
            raise RuntimeError(err)

    if size < 1024:
        raise RuntimeError('pg_dump output suspiciously small')

    finished = datetime.now()
    info = PgDumpInfo(
        path=out_path,
        sha256=sha.hexdigest(),
        size_bytes=size,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
    )
    ctx.pg_dump = info
    logger.info(f"Shared pg_dump: {size} bytes, sha256={info.sha256[:16]}...")
    return info
