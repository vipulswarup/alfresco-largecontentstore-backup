"""Email alerting for backup failures and successes."""

import logging
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
    if not getattr(config, 'email_enabled', True) or getattr(config, 'email_alert_mode', 'failure_only') == 'none':
        logging.getLogger(__name__).warning(
            "Email alerts disabled; skipping failure notification."
        )
        return
    
    customer_name = getattr(config, 'customer_name', '').strip()
    if customer_name:
        subject = f"ALERT: Alfresco Backup Failed - {customer_name} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        body_parts = [
            f"Alfresco backup process encountered failures for: {customer_name}\n",
            "=" * 70,
            f"\nFAILURE SUMMARY - {customer_name}\n",
            "=" * 70,
        ]
    else:
        subject = f"ALERT: Alfresco Backup Failed - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
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
        duration = pg_result.get('duration', 0)
        if duration >= 3600:
            body_parts.append(f"Duration: {duration/3600:.2f} hours ({duration:.0f} seconds)")
        else:
            body_parts.append(f"Duration: {duration/60:.1f} minutes ({duration:.0f} seconds)")
        
        # Add size information
        uncompressed_mb = pg_result.get('size_uncompressed_mb', 0)
        compressed_mb = pg_result.get('size_compressed_mb', 0)
        if uncompressed_mb > 0:
            if uncompressed_mb >= 1024:
                body_parts.append(f"Uncompressed size: {uncompressed_mb/1024:.2f} GB")
            else:
                body_parts.append(f"Uncompressed size: {uncompressed_mb:.2f} MB")
        if compressed_mb > 0:
            if compressed_mb >= 1024:
                body_parts.append(f"Compressed size: {compressed_mb/1024:.2f} GB")
            else:
                body_parts.append(f"Compressed size: {compressed_mb:.2f} MB")
    else:
        body_parts.append(f"\nStatus: FAILED")
        body_parts.append(f"Path: {pg_result.get('path', 'N/A')}")
        body_parts.append(f"Start time: {pg_result.get('start_time', 'unknown')}")
        duration = pg_result.get('duration', 0)
        if duration > 0:
            if duration >= 3600:
                body_parts.append(f"Duration before failure: {duration/3600:.2f} hours ({duration:.0f} seconds)")
            else:
                body_parts.append(f"Duration before failure: {duration/60:.1f} minutes ({duration:.0f} seconds)")
        
        if pg_result.get('error'):
            body_parts.append(f"\nError details:")
            body_parts.append(f"{pg_result.get('error')}")
        
        if pg_result.get('partial_size_mb'):
            body_parts.append(f"\nPartial backup size: {pg_result.get('partial_size_mb'):.2f} MB ({pg_result.get('partial_size_mb')/1024:.2f} GB)")
        
        if pg_result.get('timeout_seconds'):
            body_parts.append(f"\nTimeout limit: {pg_result.get('timeout_seconds')/3600:.2f} hours ({pg_result.get('timeout_seconds')} seconds)")
            if pg_result.get('elapsed_before_timeout'):
                body_parts.append(f"Elapsed before timeout: {pg_result.get('elapsed_before_timeout')/3600:.2f} hours")
    
    # Contentstore backup details
    body_parts.append("\n" + "=" * 70)
    body_parts.append("\nCONTENTSTORE BACKUP")
    body_parts.append("\n" + "=" * 70)
    cs_result = backup_results.get('contentstore', {})
    if cs_result.get('success'):
        body_parts.append(f"\nStatus: SUCCESS")
        body_parts.append(f"Path: {cs_result.get('path')}")
        duration = cs_result.get('duration', 0)
        if duration >= 3600:
            body_parts.append(f"Duration: {duration/3600:.2f} hours ({duration:.0f} seconds)")
        else:
            body_parts.append(f"Duration: {duration/60:.1f} minutes ({duration:.0f} seconds)")
        
        # Add size information
        total_mb = cs_result.get('total_size_mb', 0)
        additional_mb = cs_result.get('additional_size_mb', 0)
        if total_mb > 0:
            if total_mb >= 1024:
                body_parts.append(f"Total backup size: {total_mb/1024:.2f} GB")
            else:
                body_parts.append(f"Total backup size: {total_mb:.2f} MB")
        if additional_mb > 0:
            if additional_mb >= 1024:
                body_parts.append(f"Additional data backed up: {additional_mb/1024:.2f} GB")
            else:
                body_parts.append(f"Additional data backed up: {additional_mb:.2f} MB")
        
        if cs_result.get('files_transferred'):
            body_parts.append(f"Files processed: {cs_result.get('files_transferred'):,}")
    else:
        body_parts.append(f"\nStatus: FAILED")
        body_parts.append(f"Path: {cs_result.get('path', 'N/A')}")
        body_parts.append(f"Start time: {cs_result.get('start_time', 'unknown')}")
        duration = cs_result.get('duration', 0)
        if duration > 0:
            if duration >= 3600:
                body_parts.append(f"Duration before failure: {duration/3600:.2f} hours ({duration:.0f} seconds)")
            else:
                body_parts.append(f"Duration before failure: {duration/60:.1f} minutes ({duration:.0f} seconds)")
        
        if cs_result.get('error'):
            body_parts.append(f"\nError details:")
            body_parts.append(f"{cs_result.get('error')}")
        
        # Partial progress information
        if cs_result.get('partial_size_mb'):
            body_parts.append(f"\nPartial backup size: {cs_result.get('partial_size_mb'):.2f} MB ({cs_result.get('partial_size_mb')/1024:.2f} GB)")
        
        if cs_result.get('files_transferred'):
            body_parts.append(f"Files transferred before failure: {cs_result.get('files_transferred'):,}")
        
        if cs_result.get('bytes_transferred'):
            bytes_mb = cs_result.get('bytes_transferred', 0) / (1024 * 1024)
            if bytes_mb >= 1024:
                body_parts.append(f"Data transferred before failure: {bytes_mb/1024:.2f} GB ({cs_result.get('bytes_transferred'):,} bytes)")
            else:
                body_parts.append(f"Data transferred before failure: {bytes_mb:.2f} MB ({cs_result.get('bytes_transferred'):,} bytes)")
        
        if cs_result.get('timeout_seconds'):
            body_parts.append(f"\nTimeout limit: {cs_result.get('timeout_seconds')/3600:.2f} hours ({cs_result.get('timeout_seconds')} seconds)")
            if cs_result.get('elapsed_before_timeout'):
                body_parts.append(f"Elapsed before timeout: {cs_result.get('elapsed_before_timeout')/3600:.2f} hours")
        
        # Include command output if available (truncated for email)
        if cs_result.get('stderr'):
            stderr_preview = cs_result.get('stderr', '')[:500]  # First 500 chars
            body_parts.append(f"\nLast error output (preview):")
            body_parts.append(f"{stderr_preview}")
            if len(cs_result.get('stderr', '')) > 500:
                body_parts.append(f"... (truncated, see log file for full output)")
    
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


def send_success_alert(backup_results, config):
    """
    Send email alert with detailed success information.
    
    Args:
        backup_results: dict with results from all backup operations
        config: BackupConfig instance
    """
    if not getattr(config, 'email_enabled', True) or getattr(config, 'email_alert_mode', 'failure_only') == 'none':
        logging.getLogger(__name__).warning(
            "Email alerts disabled; skipping success notification."
        )
        return
    
    customer_name = getattr(config, 'customer_name', '').strip()
    if customer_name:
        subject = f"SUCCESS: Alfresco Backup Completed - {customer_name} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        body_parts = [
            f"Alfresco backup process completed successfully for: {customer_name}\n",
            "=" * 70,
            f"\nBACKUP SUMMARY - {customer_name}\n",
            "=" * 70,
        ]
    else:
        subject = f"SUCCESS: Alfresco Backup Completed - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        body_parts = [
            "Alfresco backup process completed successfully.\n",
            "=" * 70,
            "\nBACKUP SUMMARY\n",
            "=" * 70,
        ]
    
    # PostgreSQL backup details
    body_parts.append("\n" + "=" * 70)
    body_parts.append("\nPOSTGRESQL BACKUP")
    body_parts.append("\n" + "=" * 70)
    pg_result = backup_results.get('postgres', {})
    if pg_result.get('success'):
        body_parts.append(f"\nStatus: SUCCESS")
        body_parts.append(f"Path: {pg_result.get('path')}")
        body_parts.append(f"Duration: {pg_result.get('duration', 0):.2f} seconds")
        
        # Add size information
        uncompressed_mb = pg_result.get('size_uncompressed_mb', 0)
        compressed_mb = pg_result.get('size_compressed_mb', 0)
        if uncompressed_mb > 0:
            if uncompressed_mb >= 1024:
                body_parts.append(f"Uncompressed size: {uncompressed_mb/1024:.2f} GB")
            else:
                body_parts.append(f"Uncompressed size: {uncompressed_mb:.2f} MB")
        if compressed_mb > 0:
            if compressed_mb >= 1024:
                body_parts.append(f"Compressed size: {compressed_mb/1024:.2f} GB")
            else:
                body_parts.append(f"Compressed size: {compressed_mb:.2f} MB")
            if uncompressed_mb > 0:
                compression_ratio = (1 - compressed_mb / uncompressed_mb) * 100
                body_parts.append(f"Compression ratio: {compression_ratio:.1f}%")
    else:
        body_parts.append(f"\nStatus: FAILED")
        body_parts.append(f"Error: {pg_result.get('error', 'Unknown error')}")
    
    # Contentstore backup details
    body_parts.append("\n" + "=" * 70)
    body_parts.append("\nCONTENTSTORE BACKUP")
    body_parts.append("\n" + "=" * 70)
    cs_result = backup_results.get('contentstore', {})
    if cs_result.get('success'):
        body_parts.append(f"\nStatus: SUCCESS")
        body_parts.append(f"Path: {cs_result.get('path')}")
        body_parts.append(f"Duration: {cs_result.get('duration', 0):.2f} seconds")
        
        # Add size information
        total_mb = cs_result.get('total_size_mb', 0)
        additional_mb = cs_result.get('additional_size_mb', 0)
        if total_mb > 0:
            if total_mb >= 1024:
                body_parts.append(f"Total backup size: {total_mb/1024:.2f} GB")
            else:
                body_parts.append(f"Total backup size: {total_mb:.2f} MB")
        if additional_mb > 0:
            if additional_mb >= 1024:
                body_parts.append(f"Additional data backed up: {additional_mb/1024:.2f} GB")
            else:
                body_parts.append(f"Additional data backed up: {additional_mb:.2f} MB")
        else:
            body_parts.append(f"Additional data backed up: 0 MB (all files hardlinked from previous backup)")
    else:
        body_parts.append(f"\nStatus: FAILED")
        body_parts.append(f"Error: {cs_result.get('error', 'Unknown error')}")
    
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
        
        logging.info(f"Success email sent to {config.alert_email}")
    
    except Exception as e:
        logging.error(f"ERROR: Failed to send success email: {str(e)}")

