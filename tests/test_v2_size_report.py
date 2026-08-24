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


def test_generate_size_report_uses_snapshot_tags(monkeypatch):
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
            'id': 'abc123def',
            'short_id': 'abc123de',
            'time': '2026-08-24T02:00:00Z',
            'tags': [
                'run:20260824-0200-aaaa',
                'kind:complete-set',
                'bytes-processed:6089879887',
                'bytes-added:524288000',
                'solr-bytes:10737418240',
            ],
        }],
    }
    monkeypatch.setattr('alfresco_backup.v2.size_report.ResticRepository', lambda *args, **kwargs: repo)

    report = generate_size_report(config)
    assert 'Policy: local (filesystem)' in report
    assert 'Snapshot: abc123de' in report
    assert 'Run: 20260824-0200-aaaa' in report
    assert 'Full size: 5.67 GB (5807.76 MB)' in report
    assert 'Incremental: 500.00 MB' in report
    assert 'Solr indexes: 10.00 GB (10240.00 MB)' in report
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
    assert 'Full size: 1.00 GB (1024.00 MB)' in report
    assert 'Incremental: n/a' in report
    repo.stats_json.assert_called_once_with('oldsnap')
