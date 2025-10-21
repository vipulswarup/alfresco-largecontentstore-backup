"""PostgreSQL backup using pg_basebackup."""

import os
from datetime import datetime
from pathlib import Path
from subprocess_utils import SubprocessRunner, validate_path


def backup_postgres(config):
    """
    Execute PostgreSQL base backup using pg_basebackup.
    
    Returns dict with keys: success, path, error, duration, start_time
    """
    start_time = datetime.now()
    date_str = start_time.strftime('%Y-%m-%d')
    
    postgres_dir = config.backup_dir / 'postgres'
    postgres_dir.mkdir(parents=True, exist_ok=True)
    
    backup_path = postgres_dir / f'base-{date_str}'
    
    result = {
        'success': False,
        'path': str(backup_path),
        'error': None,
        'duration': 0,
        'start_time': start_time.isoformat()
    }
    
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
        result['success'] = True
        result['duration'] = subprocess_result['duration']
    else:
        result['error'] = subprocess_result['error']
    
    return result

