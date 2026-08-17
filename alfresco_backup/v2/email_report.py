"""Consolidated email for v2 backup runs."""

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .app_config import AppConfig
from .models import RunResult

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    """Render sizes in the most useful unit while preferring megabytes."""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KB"
    return f"{size_bytes} bytes"


def send_run_report(config: AppConfig, run_result: RunResult) -> None:
    if not config.email_enabled:
        return

    is_failure = run_result.status in ('failure', 'partial_success')
    if config.email_alert_mode == 'failure_only' and not is_failure:
        return
    if config.email_alert_mode == 'none':
        return

    customer = config.customer_name
    status_label = run_result.status.upper()
    prefix = f"EisenVault Backup {status_label}"
    if customer:
        subject = f"{prefix} - {customer} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    else:
        subject = f"{prefix} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    lines = [
        f"Backup run: {run_result.run_id or '(maintenance only)'}",
        f"Status: {run_result.status}",
        f"Started: {run_result.started_at}",
        f"Finished: {run_result.finished_at}",
        "",
        "=" * 60,
        "DESTINATIONS",
        "=" * 60,
    ]
    for d in run_result.destinations:
        lines.append(f"\nPolicy: {d.policy_name}")
        lines.append(f"  Success: {d.success}")
        if d.snapshot_id:
            lines.append(f"  Snapshot: {d.snapshot_id}")
        if d.duration_seconds:
            lines.append(f"  Duration: {d.duration_seconds:.1f}s")
        if d.bytes_processed:
            lines.append(f"  Processed: {_format_size(d.bytes_processed)}")
        if d.lock_contention:
            lines.append("  Lock contention: yes")
        if d.error:
            lines.append(f"  Error: {d.error}")

    if run_result.maintenance:
        lines.extend(["", "=" * 60, "MAINTENANCE", "=" * 60])
        for m in run_result.maintenance:
            lines.append(f"\nPolicy: {m.policy_name}")
            lines.append(f"  Success: {m.success}")
            if m.lock_contention:
                lines.append("  Lock contention: yes")
            if m.error:
                lines.append(f"  Error: {m.error}")

    if run_result.pg_dump:
        lines.extend([
            "",
            "=" * 60,
            "SHARED PG_DUMP",
            "=" * 60,
            f"  sha256: {run_result.pg_dump.get('sha256', '')}",
            f"  size: {_format_size(int(run_result.pg_dump.get('size_bytes', 0)))}",
        ])

    body = "\n".join(lines)
    msg = MIMEMultipart()
    msg['From'] = config.alert_from
    msg['To'] = config.alert_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
            server.starttls()
            server.login(config.smtp_user, config.smtp_password)
            server.send_message(msg)
        logger.info("V2 run report email sent")
    except Exception as e:
        logger.error(f"Failed to send v2 email: {e}")
