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


def test_destination_backup_includes_solr_and_records_added_bytes(tmp_path, monkeypatch):
    from alfresco_backup.v2.destination_task import DestinationBackupTask
    from alfresco_backup.v2.models import (
        BackupPolicy,
        EncryptionConfig,
        MaintenanceConfig,
        RunContext,
    )

    solr = tmp_path / 'solr4'
    solr.mkdir()
    (solr / 'index.bin').write_bytes(b'x' * 100)
    contentstore = tmp_path / 'contentstore'
    contentstore.mkdir()
    staging = tmp_path / 'staging'
    staging.mkdir()
    pg_path = tmp_path / 'postgres.sql.gz'
    pg_path.write_bytes(b'dump')

    policy = BackupPolicy(
        name='local',
        enabled=True,
        destination_type='filesystem',
        repository_path=str(tmp_path / 'repo'),
        credential_profile=None,
        repository_prefix=None,
        encryption=EncryptionConfig(enabled=False, password_env=None),
        backup_time='02:00',
        retention_days=7,
        maintenance=MaintenanceConfig(enabled=False, day_of_week='sunday', time='03:30'),
        priority=10,
    )
    config = MagicMock()
    config.get_profile.return_value = None
    config.global_config.restic_read_concurrency = 4
    config.contentstore_path = contentstore
    config.solr_index_paths = [solr]

    ctx = RunContext(
        run_id='run1',
        started_at=datetime.now(),
        hostname='host',
        staging_dir=staging,
        contentstore_path=contentstore,
    )
    task = DestinationBackupTask(config, policy, ctx)
    captured = {'calls': []}

    def fake_backup(paths, tags):
        captured['calls'].append((list(paths), list(tags)))
        if 'kind:solr-indexes' in tags:
            return {
                'success': True,
                'snapshot_id': 'solr1',
                'bytes_processed': 100,
                'bytes_added': 40,
                'lock_contention': False,
            }
        return {
            'success': True,
            'snapshot_id': 'snap1',
            'bytes_processed': 1000,
            'bytes_added': 200,
            'lock_contention': False,
        }

    monkeypatch.setattr(
        task.repo,
        'init',
        lambda: {'success': True, 'error': '', 'lock_contention': False},
    )
    monkeypatch.setattr(task.repo, 'backup', fake_backup)
    monkeypatch.setattr(task.repo, 'add_tags', lambda *_args, **_kwargs: {'success': True})
    monkeypatch.setattr(
        'alfresco_backup.v2.destination_task.write_run_metadata',
        lambda *_args, **_kwargs: staging / 'metadata' / 'run.json',
    )

    result = task.run(
        PgDumpInfo(
            path=pg_path,
            sha256='abc',
            size_bytes=4,
            started_at=datetime.now().isoformat(),
            finished_at=datetime.now().isoformat(),
        )
    )

    assert result.success
    assert result.bytes_added == 200
    assert result.bytes_processed == 1000
    assert result.solr_bytes_processed == 100
    assert result.solr_bytes_added == 40
    assert solr not in captured['calls'][0][0]
    assert captured['calls'][1][0] == [solr]
    assert 'kind:solr-indexes' in captured['calls'][1][1]
