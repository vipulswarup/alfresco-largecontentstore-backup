#!/usr/bin/env python3
"""
Alfresco Backup System

Main orchestrator for PostgreSQL and contentstore backups with email alerting.
"""

import sys
import logging
from datetime import datetime
from pathlib import Path
from argparse import ArgumentParser

try:
    from alfresco_backup.utils.config import BackupConfig
    from alfresco_backup.utils.lock import FileLock
    from alfresco_backup.backup.postgres import backup_postgres
    from alfresco_backup.backup.contentstore import backup_contentstore
    from alfresco_backup.backup.retention import apply_retention
    from alfresco_backup.backup.email_alert import send_failure_alert, send_success_alert
except ImportError:  # pragma: no cover
    from ..utils.config import BackupConfig
    from ..utils.lock import FileLock
    from .postgres import backup_postgres
    from .contentstore import backup_contentstore
    from .retention import apply_retention
    from .email_alert import send_failure_alert, send_success_alert


def setup_logging(backup_dir):
    """Setup file and console logging."""
    date_str = datetime.now().strftime('%Y-%m-%d')
    log_file = backup_dir / f'backup-{date_str}.log'
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return str(log_file)


def main():
    """Main backup orchestration."""
    parser = ArgumentParser(description='Alfresco backup system')
    parser.add_argument('env_file', nargs='?', help='Path to .env file (default: .env in current directory)')
    args = parser.parse_args()
    
    # Determine env file path
    env_file = args.env_file if args.env_file else '.env'
    
    try:
        # Load configuration
        print(f"Loading configuration from {env_file}...")
        config = BackupConfig(env_file)
        
        # Setup logging
        log_file = setup_logging(config.backup_dir)
        logging.info("=" * 70)
        logging.info("Alfresco backup started")
        logging.info("=" * 70)
        
        # Create backup subdirectories
        (config.backup_dir / 'contentstore').mkdir(parents=True, exist_ok=True)
        (config.backup_dir / 'postgres').mkdir(parents=True, exist_ok=True)
        
        # Acquire lock to prevent concurrent runs
        lockfile = config.backup_dir / 'backup.lock'
        
        try:
            with FileLock(str(lockfile)):
                logging.info("Lock acquired, proceeding with backup...")
                
                # Track all results
                backup_results = {
                    'log_file': log_file
                }
                
                # Step 1: PostgreSQL backup
                logging.info("-" * 70)
                logging.info("STEP 1: PostgreSQL backup")
                logging.info("-" * 70)
                pg_result = backup_postgres(config)
                backup_results['postgres'] = pg_result
                
                if pg_result['success']:
                    logging.info(f"PostgreSQL backup completed successfully")
                    logging.info(f"  Path: {pg_result['path']}")
                    logging.info(f"  Duration: {pg_result['duration']:.2f} seconds")
                    
                    # Display size information
                    uncompressed_mb = pg_result.get('size_uncompressed_mb', 0)
                    compressed_mb = pg_result.get('size_compressed_mb', 0)
                    
                    if uncompressed_mb > 0:
                        if uncompressed_mb >= 1024:
                            logging.info(f"  Uncompressed size: {uncompressed_mb/1024:.2f} GB")
                        else:
                            logging.info(f"  Uncompressed size: {uncompressed_mb:.2f} MB")
                    
                    if compressed_mb > 0:
                        if compressed_mb >= 1024:
                            logging.info(f"  Compressed size: {compressed_mb/1024:.2f} GB")
                        else:
                            logging.info(f"  Compressed size: {compressed_mb:.2f} MB")
                        
                        if uncompressed_mb > 0 and compressed_mb > 0:
                            compression_ratio = (1 - compressed_mb / uncompressed_mb) * 100
                            logging.info(f"  Compression ratio: {compression_ratio:.1f}%")
                    
                    if 'warning' in pg_result:
                        logging.warning(f"  Warning: {pg_result['warning']}")
                else:
                    logging.error(f"PostgreSQL backup FAILED")
                    logging.error(f"  Error: {pg_result['error']}")
                
                # Step 2: Contentstore backup
                logging.info("-" * 70)
                logging.info("STEP 2: Contentstore snapshot")
                logging.info("-" * 70)
                cs_result = backup_contentstore(config)
                backup_results['contentstore'] = cs_result
                
                if cs_result['success']:
                    logging.info(f"Contentstore backup completed successfully")
                    logging.info(f"  Path: {cs_result['path']}")
                    logging.info(f"  Duration: {cs_result['duration']:.2f} seconds")
                    
                    # Display size information
                    total_mb = cs_result.get('total_size_mb', 0)
                    additional_mb = cs_result.get('additional_size_mb', 0)
                    
                    if total_mb > 0:
                        if total_mb >= 1024:
                            logging.info(f"  Total backup size: {total_mb/1024:.2f} GB")
                        else:
                            logging.info(f"  Total backup size: {total_mb:.2f} MB")
                    
                    if additional_mb > 0:
                        if additional_mb >= 1024:
                            logging.info(f"  Additional data backed up: {additional_mb/1024:.2f} GB")
                        else:
                            logging.info(f"  Additional data backed up: {additional_mb:.2f} MB")
                    else:
                        logging.info(f"  Additional data backed up: 0 MB (all files hardlinked from previous backup)")
                else:
                    logging.error(f"Contentstore backup FAILED")
                    logging.error(f"  Error: {cs_result['error']}")
                
                # Step 3: Apply retention policy
                logging.info("-" * 70)
                logging.info(f"STEP 3: Retention policy ({config.retention_days} days)")
                logging.info("-" * 70)
                ret_result = apply_retention(config)
                backup_results['retention'] = ret_result
                
                if ret_result['success']:
                    logging.info(f"Retention policy applied successfully")
                    if ret_result['deleted_items']:
                        logging.info(f"  Deleted items:")
                        for item in ret_result['deleted_items']:
                            logging.info(f"    {item}")
                    else:
                        logging.info(f"  No items to delete (within retention period)")
                else:
                    logging.error(f"Retention policy FAILED")
                    logging.error(f"  Error: {ret_result['error']}")
                
                # Check if any operation failed
                any_failure = (
                    not pg_result['success'] or
                    not cs_result['success'] or
                    not ret_result['success']
                )
                
                logging.info("=" * 70)
                if any_failure:
                    logging.error("Backup completed with FAILURES")
                    if config.email_enabled and config.email_alert_mode != 'none':
                        logging.info("Sending failure alert email...")
                        send_failure_alert(backup_results, config)
                    sys.exit(1)
                else:
                    logging.info("Backup completed successfully")
                    if config.email_enabled and config.email_alert_mode == 'both':
                        logging.info("Sending success alert email...")
                        send_success_alert(backup_results, config)
                
                logging.info("=" * 70)
        
        except RuntimeError as e:
            logging.error(f"Could not acquire lock: {e}")
            sys.exit(1)
    
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nBackup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

