"""Shared PostgreSQL dump for a backup run (stream to gzip)."""

import hashlib
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path

from .app_config import AppConfig
from .models import PgDumpInfo, RunContext

logger = logging.getLogger(__name__)


def _pg_dump_binary(config: AppConfig) -> str:
    embedded = config.alf_base_dir / 'postgresql' / 'bin' / 'pg_dump'
    if embedded.exists():
        return str(embedded)
    return 'pg_dump'


def create_shared_pg_dump(config: AppConfig, ctx: RunContext) -> PgDumpInfo:
    """Stream pg_dump directly to gzip; compute sha256 and size."""
    started = datetime.now()
    postgres_dir = ctx.postgres_dir()
    postgres_dir.mkdir(parents=True, exist_ok=True)
    out_path = postgres_dir / 'postgres.sql.gz'

    pg_dump = _pg_dump_binary(config)
    env = {'PGPASSWORD': config.pgpassword, 'PATH': os.environ.get('PATH', '')}
    pg_args = [
        pg_dump,
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
