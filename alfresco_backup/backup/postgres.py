"""PostgreSQL backup using pg_basebackup."""

import os
from datetime import datetime
from pathlib import Path
try:
    from alfresco_backup.utils.subprocess_utils import SubprocessRunner, validate_path
except ImportError:  # pragma: no cover
    from ..utils.subprocess_utils import SubprocessRunner, validate_path


def backup_postgres(config):
    """
    Execute PostgreSQL base backup using pg_basebackup.
    
    Returns dict with keys: success, path, error, duration, start_time
    """
    start_time = datetime.now()
    timestamp_str = start_time.strftime('%Y-%m-%d_%H-%M-%S')
    
    postgres_dir = config.backup_dir / 'postgres'
    postgres_dir.mkdir(parents=True, exist_ok=True)
    
    backup_path = postgres_dir / f'base-{timestamp_str}'
    
    result = {
        'success': False,
        'path': str(backup_path),
        'error': None,
        'duration': 0,
        'start_time': start_time.isoformat()
    }
    
    # No need to clean up existing directory since we use timestamps for uniqueness
    
    # Validate backup path
    try:
        backup_path = validate_path(backup_path, must_exist=False)
    except ValueError as e:
        result['error'] = f"Invalid backup path: {e}"
        return result
    
    # Use embedded PostgreSQL tools to avoid version mismatch
    # Alfresco has its own PostgreSQL 9.4 binaries that match the server version
    embedded_pg_basebackup = config.alf_base_dir / 'postgresql' / 'bin' / 'pg_basebackup'
    
    if embedded_pg_basebackup.exists():
        pg_basebackup_cmd = str(embedded_pg_basebackup)
        print(f"Using embedded pg_basebackup: {pg_basebackup_cmd}")
    else:
        pg_basebackup_cmd = 'pg_basebackup'
        print(f"Embedded pg_basebackup not found, using system version: {pg_basebackup_cmd}")
    
    # Set PGPASSWORD for pg_basebackup
    env = {
        'PGPASSWORD': config.pgpassword,
        'PATH': os.environ.get('PATH', '')
    }
    
    cmd = [
        pg_basebackup_cmd,
        '-h', config.pghost,
        '-p', config.pgport,
        '-U', config.pguser,
        '-D', str(backup_path),
        '-Ft',  # tar format
        '-z',   # gzip compression
        '-P'    # progress reporting
    ]
    
    # Use common subprocess runner
    runner = SubprocessRunner(timeout=7200)  # 2 hour timeout
    subprocess_result = runner.run_command(cmd, env=env)
    
    if subprocess_result['success']:
        backup_file = backup_path / 'base.tar.gz'
        if backup_file.exists() and backup_file.stat().st_size > 1024 * 1024:
            result['success'] = True
            result['duration'] = subprocess_result['duration']
        else:
            result['error'] = (
                "pg_basebackup reported success but produced an unexpectedly small archive. "
                "Verify permissions and rerun the backup."
            )
    else:
        # Check if this is the known PostgreSQL 9.4 "postgresql.conf.backup" error
        # This error occurs after the backup completes successfully, so we can treat it as a warning
        error_msg = subprocess_result.get('error', '')
        if 'postgresql.conf.backup' in error_msg and 'Permission denied' in error_msg:
            # Verify the backup actually completed by checking for base.tar.gz
            backup_file = backup_path / 'base.tar.gz'
            if backup_file.exists() and backup_file.stat().st_size > 1024 * 1024:
                # Backup file exists and has content - treat as success with warning
                result['success'] = True
                result['duration'] = subprocess_result['duration']
                result['warning'] = 'Backup completed successfully, but encountered minor permission issue with postgresql.conf.backup (PostgreSQL 9.4 known issue)'
                print(f"Warning: {result['warning']}")
            else:
                # Backup file doesn't exist or is empty - this is a real failure
                result['error'] = subprocess_result['error']
        else:
            # Some other error - treat as failure
            result['error'] = subprocess_result['error']
    
    return result

