"""Tests for human-readable v2 backup email content."""

from alfresco_backup.v2.email_report import _destination_lines, _format_size
from alfresco_backup.v2.models import DestinationResult


def test_format_size_shows_gigabytes_and_megabytes():
    assert _format_size(6_089_879_887) == '5.67 GB (5807.76 MB)'
    assert _format_size(1024 * 1024 * 1024) == '1.00 GB (1024.00 MB)'


def test_format_size_uses_megabytes_below_one_gigabyte():
    assert _format_size(1024 * 1024) == '1.00 MB'
    assert _format_size(500 * 1024 * 1024) == '500.00 MB'


def test_format_size_uses_kilobytes_below_one_megabyte():
    assert _format_size(1536) == '1.50 KB'
    assert _format_size((1024 * 1024) - 1).endswith('KB')


def test_format_size_uses_bytes_below_one_kilobyte():
    assert _format_size(1023) == '1023 bytes'
    assert _format_size(0) == '0 bytes'


def test_destination_lines_include_processed_added_and_solr():
    dest = DestinationResult(
        policy_name='local',
        success=True,
        snapshot_id='abc123',
        duration_seconds=12.3,
        bytes_processed=6_089_879_887,
        bytes_added=524_288_000,
        solr_bytes=10_737_418_240,
    )
    lines = _destination_lines(dest)
    assert '  Processed (source size): 5.67 GB (5807.76 MB)' in lines
    assert '  Backed up this run: 500.00 MB' in lines
    assert '  Solr indexes: 10.00 GB (10240.00 MB)' in lines
