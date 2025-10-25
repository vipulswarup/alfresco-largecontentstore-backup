"""Email alerting for backup failures."""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime


def send_failure_alert(backup_results, config):
    """
    Send email alert with detailed failure information.
    
    Args:
        backup_results: dict with results from all backup operations
        config: BackupConfig instance
    """
    subject = f"ALERT: Alfresco Backup Failed - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    # Build detailed email body
    body_parts = [
        "Alfresco backup process encountered failures.\n",
        "=" * 70,
        "\nFAILURE SUMMARY\n",
        "=" * 70,
    ]
    
    # Check each operation
    failed_operations = []
    
    if not backup_results.get('postgres', {}).get('success'):
        failed_operations.append('PostgreSQL Backup')
    if not backup_results.get('contentstore', {}).get('success'):
        failed_operations.append('Contentstore Backup')
    if not backup_results.get('wal', {}).get('success'):
        failed_operations.append('WAL Archive Check')
    if not backup_results.get('retention', {}).get('success'):
        failed_operations.append('Retention Policy')
    
    body_parts.append(f"\nFailed operations: {', '.join(failed_operations)}\n")
    
    # PostgreSQL backup details
    body_parts.append("\n" + "=" * 70)
    body_parts.append("\nPOSTGRESQL BACKUP")
    body_parts.append("\n" + "=" * 70)
    pg_result = backup_results.get('postgres', {})
    if pg_result.get('success'):
        body_parts.append(f"\nStatus: SUCCESS")
        body_parts.append(f"Path: {pg_result.get('path')}")
        body_parts.append(f"Duration: {pg_result.get('duration', 0):.2f} seconds")
    else:
        body_parts.append(f"\nStatus: FAILED")
        body_parts.append(f"Path: {pg_result.get('path')}")
        body_parts.append(f"Start time: {pg_result.get('start_time', 'unknown')}")
        if pg_result.get('error'):
            body_parts.append(f"\nError details:\n{pg_result.get('error')}")
    
    # Contentstore backup details
    body_parts.append("\n" + "=" * 70)
    body_parts.append("\nCONTENTSTORE BACKUP")
    body_parts.append("\n" + "=" * 70)
    cs_result = backup_results.get('contentstore', {})
    if cs_result.get('success'):
        body_parts.append(f"\nStatus: SUCCESS")
        body_parts.append(f"Path: {cs_result.get('path')}")
        body_parts.append(f"Duration: {cs_result.get('duration', 0):.2f} seconds")
    else:
        body_parts.append(f"\nStatus: FAILED")
        body_parts.append(f"Path: {cs_result.get('path')}")
        body_parts.append(f"Start time: {cs_result.get('start_time', 'unknown')}")
        if cs_result.get('error'):
            body_parts.append(f"\nError details:\n{cs_result.get('error')}")
    
    # WAL archive details
    body_parts.append("\n" + "=" * 70)
    body_parts.append("\nWAL ARCHIVE CHECK")
    body_parts.append("\n" + "=" * 70)
    wal_result = backup_results.get('wal', {})
    if wal_result.get('success'):
        body_parts.append(f"\nStatus: SUCCESS")
        body_parts.append(f"WAL file count: {wal_result.get('wal_count', 0)}")
    else:
        body_parts.append(f"\nStatus: FAILED")
        if wal_result.get('error'):
            body_parts.append(f"\nError details:\n{wal_result.get('error')}")
    
    # Retention policy details
    body_parts.append("\n" + "=" * 70)
    body_parts.append("\nRETENTION POLICY")
    body_parts.append("\n" + "=" * 70)
    ret_result = backup_results.get('retention', {})
    if ret_result.get('success'):
        body_parts.append(f"\nStatus: SUCCESS")
        deleted = ret_result.get('deleted_items', [])
        if deleted:
            body_parts.append(f"\nDeleted items:")
            for item in deleted:
                body_parts.append(f"  - {item}")
        else:
            body_parts.append(f"\nNo items to delete (within retention period)")
    else:
        body_parts.append(f"\nStatus: FAILED")
        if ret_result.get('error'):
            body_parts.append(f"\nError details:\n{ret_result.get('error')}")
    
    # Log file location
    body_parts.append("\n" + "=" * 70)
    body_parts.append(f"\nLog file: {backup_results.get('log_file', 'unknown')}")
    body_parts.append("\n" + "=" * 70)
    
    body = '\n'.join(body_parts)
    
    # Send email
    try:
        msg = MIMEMultipart()
        msg['From'] = config.alert_from
        msg['To'] = config.alert_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain'))
        
        with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
            server.starttls()
            server.login(config.smtp_user, config.smtp_password)
            server.send_message(msg)
        
        print(f"Alert email sent to {config.alert_email}")
    
    except Exception as e:
        print(f"ERROR: Failed to send email alert: {str(e)}")

