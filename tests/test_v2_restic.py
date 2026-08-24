"""Tests for restic version compatibility."""

from unittest.mock import MagicMock

from alfresco_backup.v2.models import BackupPolicy, EncryptionConfig, MaintenanceConfig
from alfresco_backup.v2.restic import (
    INSECURE_NO_PASSWORD_MIN_VERSION,
    ResticRepository,
    _parse_backup_summary,
    restic_binary,
    supports_insecure_no_password_flag,
)


def test_insecure_flag_threshold():
    assert INSECURE_NO_PASSWORD_MIN_VERSION == (0, 17, 0)
    # Without mocking restic binary, just ensure function is callable.
    _ = supports_insecure_no_password_flag()


def test_forget_prune_uses_host_grouping(monkeypatch):
    policy = BackupPolicy(
        name='bak1week',
        enabled=True,
        destination_type='filesystem',
        repository_path='/tmp/repo',
        credential_profile=None,
        repository_prefix=None,
        encryption=EncryptionConfig(enabled=True, password_env='RESTIC_PASSWORD_BAK1WEEK'),
        backup_time='02:00',
        retention_days=7,
        maintenance=MaintenanceConfig(enabled=True, day_of_week='sunday', time='03:30'),
        priority=10,
    )
    config = MagicMock()
    config.get_profile.return_value = None
    repo = ResticRepository(policy, config, profile=None)
    captured = {'calls': []}

    def fake_run(args, timeout=None):
        captured['calls'].append(args)
        return {'success': True, 'stdout': '', 'stderr': '', 'error': None, 'lock_contention': False}

    monkeypatch.setattr(repo, '_run', fake_run)
    repo.forget_prune(7)

    assert captured['calls'] == [
        [
            'forget',
            '--keep-within', '7d',
            '--tag', 'kind:complete-set',
            '--tag', 'policy:bak1week',
            '--group-by', 'host',
        ],
        [
            'forget',
            '--keep-within', '7d',
            '--tag', 'kind:solr-indexes',
            '--tag', 'policy:bak1week',
            '--group-by', 'host',
            '--prune',
        ],
    ]


def test_repository_sets_restic_read_concurrency():
    policy = BackupPolicy(
        name='bak1week',
        enabled=True,
        destination_type='filesystem',
        repository_path='/tmp/repo',
        credential_profile=None,
        repository_prefix=None,
        encryption=EncryptionConfig(enabled=True, password_env='RESTIC_PASSWORD_BAK1WEEK'),
        backup_time='02:00',
        retention_days=7,
        maintenance=MaintenanceConfig(enabled=True, day_of_week='sunday', time='03:30'),
        priority=10,
    )
    config = MagicMock()
    config.global_config.restic_read_concurrency = 8
    config.get_profile.return_value = None

    repo = ResticRepository(policy, config, profile=None)

    assert repo._env['RESTIC_READ_CONCURRENCY'] == '8'


def test_restic_binary_uses_explicit_path_for_minimal_cron_environment(tmp_path, monkeypatch):
    binary = tmp_path / 'restic'
    binary.write_text('#!/bin/sh\n')
    binary.chmod(0o755)
    monkeypatch.setenv('RESTIC_BINARY', str(binary))
    monkeypatch.setattr('alfresco_backup.v2.restic.shutil.which', lambda _name: None)

    assert restic_binary() == str(binary)


def _policy():
    return BackupPolicy(
        name='bak1week',
        enabled=True,
        destination_type='filesystem',
        repository_path='/tmp/repo',
        credential_profile=None,
        repository_prefix=None,
        encryption=EncryptionConfig(enabled=True, password_env='RESTIC_PASSWORD_BAK1WEEK'),
        backup_time='02:00',
        retention_days=7,
        maintenance=MaintenanceConfig(enabled=True, day_of_week='sunday', time='03:30'),
        priority=10,
    )


def test_parse_backup_summary_reads_processed_and_added():
    stdout = (
        '{"message_type":"status","percent_done":1}\n'
        '{"message_type":"summary","total_bytes_processed":900000000000,'
        '"data_added":524288000,"data_added_packed":400000000,"snapshot_id":"abc"}\n'
    )
    summary = _parse_backup_summary(stdout)
    assert summary['snapshot_id'] == 'abc'
    assert summary['total_bytes_processed'] == 900000000000
    assert summary['data_added'] == 524288000


def test_add_tags_uses_restic_tag_add(monkeypatch):
    config = MagicMock()
    config.global_config.restic_read_concurrency = 4
    repo = ResticRepository(_policy(), config, profile=None)
    captured = {}

    def fake_run(args, timeout=None):
        captured['args'] = args
        captured['timeout'] = timeout
        return {'success': True, 'stdout': '', 'stderr': '', 'error': None, 'lock_contention': False}

    monkeypatch.setattr(repo, '_run', fake_run)
    repo.add_tags('snapid', ['bytes-processed:10', 'bytes-added:2'])

    assert captured['args'] == [
        'tag',
        '--add', 'bytes-processed:10',
        '--add', 'bytes-added:2',
        'snapid',
    ]


def test_backup_parses_bytes_added_from_summary(monkeypatch, tmp_path):
    config = MagicMock()
    config.global_config.restic_read_concurrency = 4
    repo = ResticRepository(_policy(), config, profile=None)

    def fake_run(args, timeout=None):
        return {
            'success': True,
            'stdout': (
                '{"message_type":"summary","total_bytes_processed":100,'
                '"data_added":20,"snapshot_id":"s1"}\n'
            ),
            'stderr': '',
            'error': None,
            'lock_contention': False,
        }

    monkeypatch.setattr(repo, '_run', fake_run)
    result = repo.backup([tmp_path], ['kind:complete-set'])
    assert result['snapshot_id'] == 's1'
    assert result['bytes_processed'] == 100
    assert result['bytes_added'] == 20
