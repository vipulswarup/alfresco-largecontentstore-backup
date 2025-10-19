"""PostgreSQL backup using pg_basebackup."""

import subprocess
import time
from datetime import datetime
from pathlib import Path


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
    
    # Set PGPASSWORD for pg_basebackup
    env = {
        'PGPASSWORD': config.pgpassword,
        'PATH': subprocess.os.environ.get('PATH', '')
    }
    
    cmd = [
        'pg_basebackup',
        '-h', config.pghost,
        '-p', config.pgport,
        '-U', config.pguser,
        '-D', str(backup_path),
        '-Ft',  # tar format
        '-z',   # gzip compression
        '-P'    # progress reporting
    ]
    
    try:
        start = time.time()
        process = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=7200  # 2 hour timeout
        )
        duration = time.time() - start
        
        if process.returncode != 0:
            result['error'] = f"pg_basebackup failed with exit code {process.returncode}\n"
            result['error'] += f"STDOUT: {process.stdout}\n"
            result['error'] += f"STDERR: {process.stderr}"
        else:
            result['success'] = True
            result['duration'] = duration
    
    except subprocess.TimeoutExpired:
        result['error'] = "pg_basebackup timed out after 2 hours"
    except FileNotFoundError:
        result['error'] = "pg_basebackup command not found. Ensure PostgreSQL client tools are installed."
    except Exception as e:
        result['error'] = f"Unexpected error during PostgreSQL backup: {str(e)}"
    
    return result

