"""Tests for on-demand backup size reporting."""

from unittest.mock import MagicMock

from alfresco_backup.v2.size_report import (
    SIZE_TAG_ADDED,
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
    ]
    assert parse_size_tag(tags, SIZE_TAG_PROCESSED) == 900000000000
    assert parse_size_tag(tags, SIZE_TAG_ADDED) == 524288000
    assert parse_size_tag(tags, SIZE_TAG_SOLR) == 10737418240
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
    assert 'Contentstore: 5.67 GB (5807.76 MB)' in report
    assert 'Solr indexes: 10.00 GB (10240.00 MB)' in report
    assert 'Incremental backups' in report
    assert '2026-08-24' in report
    assert 'Contentstore: 500.00 MB' in report
    assert 'Solr indexes: 100.00 MB' in report
    repo.stats_json.assert_not_called()


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
    assert 'None yet.' in report
    repo.stats_json.assert_called_once_with('oldsnap')
