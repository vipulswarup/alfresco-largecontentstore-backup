"""Tests for human-readable v2 backup email content."""

from unittest.mock import MagicMock

from alfresco_backup.v2.email_report import (
    _destination_lines,
    _format_size,
    send_run_report,
)
from alfresco_backup.v2.models import DestinationResult, RunResult
from alfresco_backup.v2.size_report_pdf import build_size_report_pdf


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
        solr_bytes_processed=10_737_418_240,
        solr_bytes_added=104_857_600,
    )
    lines = _destination_lines(dest)
    assert '  Contentstore' in lines
    assert '    Processed: 5.67 GB (5807.76 MB)' in lines
    assert '    Backed up this run: 500.00 MB' in lines
    assert '  Solr indexes' in lines
    assert '    Processed: 10.00 GB (10240.00 MB)' in lines
    assert '    Backed up this run: 100.00 MB' in lines


def test_build_size_report_pdf_contains_report_text():
    report = (
        "Last full backup\n"
        "  Date: 2026-08-17 07:10:12\n"
        "  Contentstore: 914.21 GB (936146.23 MB)\n"
        "Incremental backups\n"
        "  2026-08-25\n"
        "    Contentstore: 593.78 MB\n"
    )
    pdf = build_size_report_pdf(report)
    assert pdf.startswith(b'%PDF-1.4')
    assert b'Last full backup' in pdf
    assert b'2026-08-25' in pdf
    assert pdf.rstrip().endswith(b'%%EOF')


def test_send_run_report_attaches_size_report_pdf_without_changing_body(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            return None

        def login(self, *args):
            return None

        def send_message(self, msg):
            sent['msg'] = msg

    config = MagicMock()
    config.email_enabled = True
    config.email_alert_mode = 'both'
    config.customer_name = 'Acme'
    config.alert_from = 'backups@example.com'
    config.alert_email = 'ops@example.com'
    config.smtp_host = 'smtp.example.com'
    config.smtp_port = 587
    config.smtp_user = 'user'
    config.smtp_password = 'secret'

    report = (
        "Last full backup\n"
        "  Date: 2026-08-17 07:10:12\n"
        "Incremental backups\n"
        "  2026-08-25\n"
        "    Contentstore: 593.78 MB\n"
    )
    monkeypatch.setattr('alfresco_backup.v2.email_report.smtplib.SMTP', FakeSMTP)
    monkeypatch.setattr(
        'alfresco_backup.v2.size_report.generate_size_report',
        lambda _config: report,
    )

    send_run_report(
        config,
        RunResult(
            run_id='run1',
            status='success',
            started_at='2026-08-26T02:00:00',
            finished_at='2026-08-26T03:00:00',
            destinations=[
                DestinationResult(policy_name='daily-backup', success=True, snapshot_id='abc'),
            ],
        ),
    )

    msg = sent['msg']
    body = msg.get_payload()[0].get_payload()
    assert 'DESTINATIONS' in body
    assert 'Last full backup' not in body
    attachment = msg.get_payload()[1]
    assert attachment.get_content_type() == 'application/pdf'
    filename = attachment.get_filename()
    assert filename.startswith('backup-size-report-')
    assert filename.endswith('.pdf')
    pdf = attachment.get_payload(decode=True)
    assert pdf.startswith(b'%PDF-1.4')
    assert b'Last full backup' in pdf
    assert b'2026-08-25' in pdf
