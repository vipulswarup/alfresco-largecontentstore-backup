"""Unit tests for v2 config, schedule, migration, restore planning."""

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from alfresco_backup.v2.app_config import AppConfig
from alfresco_backup.v2.integrity import content_url_to_path, query_content_urls
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
    assert cfg.global_config.restic_read_concurrency == 4


def test_app_config_rejects_invalid_restic_read_concurrency(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    policies = tmp_path / 'backup-policies.yml'
    (tmp_path / 'alf_data' / 'contentstore').mkdir(parents=True)
    env.write_text(
        f"PGHOST=localhost\nPGPORT=5432\nPGUSER=a\nPGPASSWORD=b\n"
        f"ALF_BASE_DIR={tmp_path}\n"
    )
    policies.write_text(yaml.dump({
        'config_version': 1,
        'global': {
            'staging_dir': str(tmp_path / 'staging'),
            'restic_read_concurrency': 0,
        },
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

    with pytest.raises(ValueError, match='restic_read_concurrency'):
        AppConfig(str(env), str(policies))


def test_app_config_rejects_duplicate_enabled_filesystem_repositories(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    policies = tmp_path / 'backup-policies.yml'
    cs = tmp_path / 'alf_data' / 'contentstore'
    cs.mkdir(parents=True)
    env.write_text(
        f"PGHOST=localhost\nPGPORT=5432\nPGUSER=a\nPGPASSWORD=b\n"
        f"ALF_BASE_DIR={tmp_path}\n"
    )
    repo = tmp_path / 'repo'
    policies.write_text(yaml.dump({
        'config_version': 1,
        'global': {'staging_dir': str(tmp_path / 'staging'), 'max_parallel_destinations': 2},
        'credential_profiles': [],
        'backup_policies': [
            {
                'name': 'local',
                'enabled': True,
                'destination_type': 'filesystem',
                'repository_path': str(repo),
                'encryption': {'enabled': False, 'password_env': None},
                'backup_time': '02:00',
                'retention_days': 7,
                'priority': 10,
            },
            {
                'name': 'local-copy',
                'enabled': True,
                'destination_type': 'filesystem',
                'repository_path': str(repo),
                'encryption': {'enabled': False, 'password_env': None},
                'backup_time': '02:30',
                'retention_days': 14,
                'priority': 11,
            },
        ],
    }))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match='Duplicate enabled filesystem destinations'):
        AppConfig(str(env), str(policies))


def test_app_config_separates_source_and_restore_dirs(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    restore = tmp_path / 'restore'
    (source / 'alf_data' / 'contentstore').mkdir(parents=True)
    restore.mkdir()
    env = tmp_path / '.env'
    policies = tmp_path / 'backup-policies.yml'
    env.write_text(
        f"PGHOST=localhost\nPGPORT=5432\nPGUSER=a\nPGPASSWORD=b\n"
        f"EISENVAULT_SOURCE_DIR={source}\n"
        f"EISENVAULT_RESTORE_DIR={restore}\n"
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
    assert cfg.source_alf_base_dir == source
    assert cfg.restore_alf_base_dir == restore
    assert cfg.contentstore_path == source / 'alf_data' / 'contentstore'
    assert cfg.restore_contentstore_path == restore / 'alf_data' / 'contentstore'
    assert cfg.solr_index_paths == []


def test_app_config_discovers_solr_index_paths(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    (source / 'alf_data' / 'contentstore').mkdir(parents=True)
    solr4 = source / 'alf_data' / 'solr4'
    solr4.mkdir()
    env = tmp_path / '.env'
    policies = tmp_path / 'backup-policies.yml'
    env.write_text(
        f"PGHOST=localhost\nPGPORT=5432\nPGUSER=a\nPGPASSWORD=b\n"
        f"EISENVAULT_SOURCE_DIR={source}\n"
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
    assert cfg.solr_index_paths == [solr4]


def test_app_config_restore_mode_allows_deleted_source_dir(tmp_path, monkeypatch):
    missing_source = tmp_path / 'deleted-source'
    restore = tmp_path / 'restore'
    restore.mkdir()
    env = tmp_path / '.env'
    policies = tmp_path / 'backup-policies.yml'
    env.write_text(
        f"PGHOST=localhost\nPGPORT=5432\nPGUSER=a\nPGPASSWORD=b\n"
        f"EISENVAULT_SOURCE_DIR={missing_source}\n"
        f"EISENVAULT_RESTORE_DIR={restore}\n"
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
    cfg = AppConfig(str(env), str(policies), mode='restore')
    assert cfg.restore_alf_base_dir == restore


def test_app_config_backup_mode_requires_source_contentstore(tmp_path, monkeypatch):
    missing_source = tmp_path / 'deleted-source'
    restore = tmp_path / 'restore'
    restore.mkdir()
    env = tmp_path / '.env'
    policies = tmp_path / 'backup-policies.yml'
    env.write_text(
        f"PGHOST=localhost\nPGPORT=5432\nPGUSER=a\nPGPASSWORD=b\n"
        f"EISENVAULT_SOURCE_DIR={missing_source}\n"
        f"EISENVAULT_RESTORE_DIR={restore}\n"
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
    with pytest.raises(ValueError, match='EISENVAULT_SOURCE_DIR does not exist'):
        AppConfig(str(env), str(policies))


def test_content_url_mapping(tmp_path):
    root = tmp_path / 'contentstore'
    p = content_url_to_path('store://2024/01/15/10/30/abc.bin', root)
    assert p == root / '2024/01/15/10/30/abc.bin'


def test_query_content_urls_only_checks_referenced_content(monkeypatch, tmp_path):
    class Config:
        pgpassword = 'secret'
        pghost = 'localhost'
        pgport = '5432'
        pguser = 'alfresco'
        pgdatabase = 'alfresco'
        restore_alf_base_dir = tmp_path

    captured = {}

    def fake_run(cmd, env, capture_output, text, timeout):
        captured['cmd'] = cmd

        class Proc:
            returncode = 0
            stdout = 'store://2026/7/2/12/8/live.bin\n'
            stderr = ''

        return Proc()

    monkeypatch.setattr('alfresco_backup.v2.integrity.subprocess.run', fake_run)

    assert query_content_urls(Config()) == ['store://2026/7/2/12/8/live.bin']
    sql = captured['cmd'][-1]
    assert 'JOIN alf_content_data cd ON cd.content_url_id = cu.id' in sql
    assert 'SELECT DISTINCT cu.content_url' in sql


def test_tag_value():
    tags = ['app:alfresco-backup', 'run:abc-123', 'kind:complete-set']
    assert _tag_value(tags, 'run:') == 'abc-123'
