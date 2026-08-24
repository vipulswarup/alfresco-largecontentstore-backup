"""Tests for PostgreSQL client version selection."""

from pathlib import Path

from alfresco_backup.utils.pg_client import (
    is_version_mismatch,
    missing_client_error,
    parse_pg_version,
    parse_server_version_num,
    select_postgres_clients,
)


def test_parse_pg_version_from_pg_dump_output():
    assert parse_pg_version('pg_dump.bin (PostgreSQL) 9.4.12') == (9, 4)
    assert parse_pg_version(
        'pg_dump (PostgreSQL) 12.22 (Ubuntu 12.22-3.pgdg24.04+1)'
    ) == (12, 22)


def test_parse_server_version_num():
    assert parse_server_version_num('90412') == (9, 4)
    assert parse_server_version_num('120022') == (12, 22)
    assert parse_server_version_num('160004') == (16, 4)


def test_is_version_mismatch_detects_pg_dump_abort():
    stderr = (
        'pg_dump.bin: server version: 12.22 (Ubuntu 12.22-3.pgdg24.04+1); '
        'pg_dump.bin version: 9.4.12\n'
        'pg_dump.bin: aborting because of server version mismatch'
    )
    assert is_version_mismatch(stderr)


def _write_client(path: Path, version: str) -> None:
    path.write_text(f'#!/bin/sh\necho "pg_dump (PostgreSQL) {version}"\n')
    path.chmod(0o755)


def test_select_skips_older_embedded_pg_dump(tmp_path, monkeypatch):
    old = tmp_path / 'embedded' / 'pg_dump'
    new = tmp_path / 'system' / 'pg_dump'
    old.parent.mkdir()
    new.parent.mkdir()
    _write_client(old, '9.4.12')
    _write_client(new, '12.22')

    monkeypatch.setattr('alfresco_backup.utils.pg_client.PG_BIN_GLOBS', ())
    monkeypatch.setattr('alfresco_backup.utils.pg_client.shutil.which', lambda _name: str(new))
    monkeypatch.setattr(
        'alfresco_backup.utils.pg_client.query_server_version',
        lambda *_args, **_kwargs: (12, 22),
    )

    compatible, found, server = select_postgres_clients(
        'pg_dump',
        extra_paths=[old],
        host='localhost',
        port='5432',
        user='alfresco',
        password='secret',
        database='alfresco',
    )

    assert server == (12, 22)
    assert {c.version for c in found} == {(9, 4), (12, 22)}
    assert compatible[0].path == str(new)
    assert all(c.version[0] >= 12 for c in compatible)


def test_missing_client_error_names_server_package():
    from alfresco_backup.utils.pg_client import PgClient

    message = missing_client_error(
        'pg_dump',
        (12, 22),
        [PgClient(path='/opt/alfresco/postgresql/bin/pg_dump', version=(9, 4))],
    )
    assert 'postgresql-client-12' in message
    assert '9.4' in message
