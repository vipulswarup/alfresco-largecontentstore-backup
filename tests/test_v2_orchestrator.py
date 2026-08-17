"""Tests for v2 backup orchestration lifecycle."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from alfresco_backup.v2 import orchestrator
from alfresco_backup.v2.models import DestinationResult, PgDumpInfo


def test_run_backup_removes_run_staging_after_success(tmp_path, monkeypatch):
    staging_root = tmp_path / 'staging'
    policy = MagicMock(name='policy')
    policy.name = 'local'
    policy.backup_time = '02:00'
    policy.maintenance.enabled = False

    config = MagicMock()
    config.global_config.staging_dir = staging_root
    config.enabled_policies.return_value = [policy]
    config.contentstore_path = tmp_path / 'contentstore'

    def fake_pg_dump(_config, ctx):
        path = ctx.postgres_dir() / 'postgres.sql.gz'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'pg dump')
        return PgDumpInfo(
            path=path,
            sha256='abc',
            size_bytes=7,
            started_at=datetime.now().isoformat(),
            finished_at=datetime.now().isoformat(),
        )

    def fake_destinations(_config, _policies, ctx, _pg_dump):
        copied_dump = ctx.staging_dir / 'local' / 'postgres' / 'postgres.sql.gz'
        copied_dump.parent.mkdir(parents=True)
        copied_dump.write_bytes(b'copied pg dump')
        return [DestinationResult(policy_name='local', success=True)]

    monkeypatch.setattr(orchestrator, 'create_shared_pg_dump', fake_pg_dump)
    monkeypatch.setattr(orchestrator, '_run_destinations_parallel', fake_destinations)
    monkeypatch.setattr(orchestrator, '_run_maintenance', lambda *_args: [])
    monkeypatch.setattr(orchestrator, 'send_run_report', lambda *_args: None)

    result = orchestrator.run_backup(config, force=True)

    assert result.status == 'success'
    assert staging_root.exists()
    assert list(staging_root.iterdir()) == []


def test_run_backup_removes_run_staging_after_failure(tmp_path, monkeypatch):
    staging_root = tmp_path / 'staging'
    policy = MagicMock(name='policy')
    policy.name = 'local'
    policy.backup_time = '02:00'
    policy.maintenance.enabled = False

    config = MagicMock()
    config.global_config.staging_dir = staging_root
    config.enabled_policies.return_value = [policy]
    config.contentstore_path = tmp_path / 'contentstore'

    def failing_pg_dump(_config, ctx):
        partial_dump = ctx.postgres_dir() / 'postgres.sql.gz'
        partial_dump.parent.mkdir(parents=True)
        partial_dump.write_bytes(b'partial pg dump')
        raise ValueError('pg_dump failed')

    monkeypatch.setattr(orchestrator, 'create_shared_pg_dump', failing_pg_dump)

    try:
        orchestrator.run_backup(config, force=True)
    except ValueError as exc:
        assert str(exc) == 'pg_dump failed'
    else:
        raise AssertionError('Expected the failed dump to be raised')

    assert staging_root.exists()
    assert list(staging_root.iterdir()) == []
