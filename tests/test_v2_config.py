"""Unit tests for v2 config, schedule, migration, restore planning."""

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from alfresco_backup.v2.app_config import AppConfig
from alfresco_backup.v2.integrity import content_url_to_path
from alfresco_backup.v2.migration import migrate_legacy_env, needs_migration
from alfresco_backup.v2.restore_planner import RestorePlanner, _tag_value
from alfresco_backup.v2.schedule import (
    is_backup_due,
    is_maintenance_due,
    maintenance_cron_expression,
    parse_hhmm,
)


def test_parse_hhmm():
    assert parse_hhmm('02:30').hour == 2
    assert parse_hhmm('02:30').minute == 30


def test_backup_due_within_window():
    now = datetime(2025, 5, 18, 2, 0, 30)
    assert is_backup_due('02:00', now) is True
    assert is_backup_due('03:00', now) is False


def test_maintenance_due_sunday():
    now = datetime(2025, 5, 18, 3, 30, 0)  # Sunday
    assert is_maintenance_due(True, 'sunday', '03:30', now) is True
    assert is_maintenance_due(True, 'monday', '03:30', now) is False


def test_maintenance_cron_expression():
    assert maintenance_cron_expression('sunday', '03:30') == '30 3 * * 0'
    assert maintenance_cron_expression('monday', '05:15') == '15 5 * * 1'


def test_migration_from_legacy_env(tmp_path):
    alf = tmp_path / 'alf'
    (alf / 'alf_data' / 'contentstore').mkdir(parents=True)
    env = tmp_path / '.env'
    policies = tmp_path / 'backup-policies.yml'
    env.write_text(
        f"PGHOST=localhost\nPGPORT=5432\nPGUSER=a\nPGPASSWORD=b\n"
        f"ALF_BASE_DIR={alf}\nBACKUP_DIR=/mnt/backups\nRETENTION_DAYS=15\n"
    )
    created, _ = migrate_legacy_env(env, policies)
    assert created
    assert policies.exists()
    doc = yaml.safe_load(policies.read_text())
    assert doc['migrated_from_legacy'] is True
    assert doc['backup_policies'][0]['destination_type'] == 'filesystem'


def test_app_config_validation(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    policies = tmp_path / 'backup-policies.yml'
    cs = tmp_path / 'alf_data' / 'contentstore'
    cs.mkdir(parents=True)
    env.write_text(
        f"PGHOST=localhost\nPGPORT=5432\nPGUSER=a\nPGPASSWORD=b\n"
        f"ALF_BASE_DIR={tmp_path}\n"
    )
    policies.write_text(yaml.dump({
        'config_version': 1,
        'global': {'staging_dir': str(tmp_path / 'staging'), 'max_parallel_destinations': 2},
        'credential_profiles': [],
        'backup_policies': [{
            'name': 'local',
            'enabled': True,
            'destination_type': 'filesystem',
            'repository_path': str(tmp_path / 'repo'),
            'encryption': {'enabled': False, 'password_env': None},
            'backup_time': '02:00',
            'retention_days': 7,
            'priority': 10,
        }],
    }))
    monkeypatch.chdir(tmp_path)
    cfg = AppConfig(str(env), str(policies))
    assert len(cfg.enabled_policies()) == 1


def test_content_url_mapping(tmp_path):
    root = tmp_path / 'contentstore'
    p = content_url_to_path('store://2024/01/15/10/30/abc.bin', root)
    assert p == root / '2024/01/15/10/30/abc.bin'


def test_tag_value():
    tags = ['app:alfresco-backup', 'run:abc-123', 'kind:complete-set']
    assert _tag_value(tags, 'run:') == 'abc-123'
