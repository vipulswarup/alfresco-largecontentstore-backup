"""Tests for restic version compatibility."""

from unittest.mock import MagicMock

from alfresco_backup.v2.models import BackupPolicy, EncryptionConfig, MaintenanceConfig
from alfresco_backup.v2.restic import (
    INSECURE_NO_PASSWORD_MIN_VERSION,
    ResticRepository,
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
    captured = {}

    def fake_run(args, timeout=None):
        captured['args'] = args
        return {'success': True, 'stdout': '', 'stderr': '', 'error': None, 'lock_contention': False}

    monkeypatch.setattr(repo, '_run', fake_run)
    repo.forget_prune(7)

    assert captured['args'] == [
        'forget',
        '--keep-within', '7d',
        '--tag', 'kind:complete-set',
        '--tag', 'policy:bak1week',
        '--group-by', 'host',
        '--prune',
    ]
