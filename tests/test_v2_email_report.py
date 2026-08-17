"""Tests for human-readable v2 backup email content."""

from alfresco_backup.v2.email_report import _format_size


def test_format_size_prefers_megabytes():
    assert _format_size(6_089_879_887) == '5807.76 MB'
    assert _format_size(1024 * 1024) == '1.00 MB'


def test_format_size_uses_kilobytes_below_one_megabyte():
    assert _format_size(1536) == '1.50 KB'
    assert _format_size((1024 * 1024) - 1).endswith('KB')


def test_format_size_uses_bytes_below_one_kilobyte():
    assert _format_size(1023) == '1023 bytes'
    assert _format_size(0) == '0 bytes'
