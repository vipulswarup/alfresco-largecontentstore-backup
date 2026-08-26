"""Tests for on-demand backup size reporting."""

from unittest.mock import MagicMock

from alfresco_backup.v2.size_report import (
    SIZE_TAG_ADDED,
    SIZE_TAG_DB,
    SIZE_TAG_PROCESSED,
    SIZE_TAG_SOLR,
    generate_size_report,
    parse_size_tag,
)


def test_parse_size_tag():
    tags = [
        'kind:complete-set',
        'bytes-processed:900000000000',
        'bytes-added:524288000',
        'solr-bytes:10737418240',
        'bytes-db:5242880',
    ]
    assert parse_size_tag(tags, SIZE_TAG_PROCESSED) == 900000000000
    assert parse_size_tag(tags, SIZE_TAG_ADDED) == 524288000
    assert parse_size_tag(tags, SIZE_TAG_SOLR) == 10737418240
    assert parse_size_tag(tags, SIZE_TAG_DB) == 5242880
    assert parse_size_tag(tags, 'missing:') is None


def test_generate_size_report_shows_full_backup_and_incrementals(monkeypatch):
    policy = MagicMock()
    policy.name = 'local'
    policy.destination_type = 'filesystem'
    policy.credential_profile = None

    config = MagicMock()
    config.enabled_policies.return_value = [policy]
    config.get_profile.return_value = None

    repo = MagicMock()
    repo.snapshots_json.return_value = {
        'success': True,
        'snapshots': [
            {
                'id': 'fullsnap',
                'short_id': 'fullsnap',
                'time': '2026-08-20T02:00:00Z',
                'tags': [
                    'run:20260820-0200-aaaa',
                    'kind:complete-set',
                    'bytes-processed:6089879887',
                    'bytes-added:6089879887',
                    'bytes-db:5242880',
                ],
            },
            {
                'id': 'incsnap',
                'short_id': 'incsnap',
                'time': '2026-08-24T02:00:00Z',
                'tags': [
                    'run:20260824-0200-bbbb',
                    'kind:complete-set',
                    'bytes-processed:6200000000',
                    'bytes-added:524288000',
                    'bytes-db:3145728',
                ],
            },
            {
                'id': 'solrfull',
                'short_id': 'solrfull',
                'time': '2026-08-20T02:10:00Z',
                'tags': [
                    'kind:solr-indexes',
                    'bytes-processed:10737418240',
                    'bytes-added:10737418240',
                ],
            },
            {
                'id': 'solrinc',
                'short_id': 'solrinc',
                'time': '2026-08-24T02:10:00Z',
                'tags': [
                    'kind:solr-indexes',
                    'bytes-processed:10737418240',
                    'bytes-added:104857600',
                ],
            },
        ],
    }
    monkeypatch.setattr('alfresco_backup.v2.size_report.ResticRepository', lambda *args, **kwargs: repo)

    report = generate_size_report(config)
    assert 'Policy: local (filesystem)' in report
    assert 'Last full backup' in report
    assert 'Date: 2026-08-20 02:00:00' in report
    assert 'Contentstore: 5.67 GB (5802.76 MB)' in report
    assert 'Database: 5.00 MB' in report
    assert 'Solr indexes: 10.00 GB (10240.00 MB)' in report
    assert 'Incremental backups' in report
    assert '2026-08-24' in report
    assert 'Contentstore: 500.00 MB' in report
    assert 'Database: 3.00 MB' in report
    assert 'Solr indexes: 100.00 MB' in report
    repo.stats_json.assert_not_called()
    repo.dump_text.assert_not_called()


def test_generate_size_report_falls_back_to_restic_stats(monkeypatch):
    policy = MagicMock()
    policy.name = 'local'
    policy.destination_type = 'filesystem'
    policy.credential_profile = None

    config = MagicMock()
    config.enabled_policies.return_value = [policy]
    config.get_profile.return_value = None

    repo = MagicMock()
    repo.snapshots_json.return_value = {
        'success': True,
        'snapshots': [{
            'id': 'oldsnap',
            'short_id': 'oldsnap1',
            'time': '2026-08-01T02:00:00Z',
            'tags': ['kind:complete-set'],
        }],
    }
    repo.stats_json.return_value = {
        'success': True,
        'stats': {'total_size': 1024 * 1024 * 1024},
    }
    monkeypatch.setattr('alfresco_backup.v2.size_report.ResticRepository', lambda *args, **kwargs: repo)

    report = generate_size_report(config)
    assert 'Last full backup' in report
    assert 'Date: 2026-08-01 02:00:00' in report
    assert 'Contentstore: 1.00 GB (1024.00 MB)' in report
    assert 'Database: n/a' in report
    assert 'None yet.' in report
    repo.stats_json.assert_called_once_with('oldsnap')


def test_generate_size_report_reads_db_size_from_run_json(monkeypatch, tmp_path):
    policy = MagicMock()
    policy.name = 'local'
    policy.destination_type = 'filesystem'
    policy.credential_profile = None

    staging = tmp_path / 'staging'
    config = MagicMock()
    config.enabled_policies.return_value = [policy]
    config.get_profile.return_value = None
    config.global_config.staging_dir = staging

    repo = MagicMock()
    repo.snapshots_json.return_value = {
        'success': True,
        'snapshots': [{
            'id': 'fullsnap',
            'short_id': 'fullsnap',
            'time': '2026-08-24T09:28:03Z',
            'tags': [
                'run:20260824-1458-aaaa',
                'kind:complete-set',
                'bytes-processed:24117248',
                'bytes-added:24117248',
            ],
        }],
    }
    repo.dump_text.return_value = {
        'success': True,
        'stdout': '{"pg_dump": {"size_bytes": 10485760}}',
    }
    monkeypatch.setattr('alfresco_backup.v2.size_report.ResticRepository', lambda *args, **kwargs: repo)

    report = generate_size_report(config)
    assert 'Contentstore: 13.00 MB' in report
    assert 'Database: 10.00 MB' in report
    repo.dump_text.assert_called_once_with(
        'fullsnap',
        str(staging / '20260824-1458-aaaa' / 'local' / 'metadata' / 'run.json'),
    )


def test_generate_size_report_sorts_mixed_restic_timestamps(monkeypatch):
    policy = MagicMock()
    policy.name = 'local'
    policy.destination_type = 'filesystem'
    policy.credential_profile = None

    config = MagicMock()
    config.enabled_policies.return_value = [policy]
    config.get_profile.return_value = None

    repo = MagicMock()
    repo.snapshots_json.return_value = {
        'success': True,
        'snapshots': [
            {
                'id': 'fullsnap',
                'short_id': 'fullsnap',
                'time': '2026-08-20T02:00:00Z',
                'tags': [
                    'kind:complete-set',
                    'bytes-processed:1048576',
                    'bytes-added:1048576',
                    'bytes-db:1',
                ],
            },
            {
                'id': 'incsnap',
                'short_id': 'incsnap',
                'time': '2026-08-24T14:58:03.382418538Z',
                'tags': [
                    'kind:complete-set',
                    'bytes-processed:2097152',
                    'bytes-added:1048576',
                    'bytes-db:1',
                ],
            },
            {
                'id': 'naivesnap',
                'short_id': 'naivesnap',
                'time': '2026-08-21T03:00:00',
                'tags': [
                    'kind:complete-set',
                    'bytes-processed:1572864',
                    'bytes-added:524288',
                    'bytes-db:1',
                ],
            },
        ],
    }
    monkeypatch.setattr('alfresco_backup.v2.size_report.ResticRepository', lambda *args, **kwargs: repo)

    report = generate_size_report(config)
    assert 'Date: 2026-08-20 02:00:00' in report
    assert '2026-08-24' in report
    assert '2026-08-21' in report
