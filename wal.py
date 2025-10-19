"""WAL archive monitoring."""

import subprocess
from pathlib import Path


def check_wal_archive(config):
    """
    Check WAL archive directory and return information about archived files.
    
    Returns dict with keys: success, wal_count, error, latest_files
    """
    wal_dir = config.backup_dir / 'pg_wal'
    wal_dir.mkdir(parents=True, exist_ok=True)
    
    result = {
        'success': False,
        'wal_count': 0,
        'error': None,
        'latest_files': []
    }
    
    try:
        # List WAL files
        cmd = ['ls', '-lht', str(wal_dir)]
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if process.returncode != 0:
            result['error'] = f"Failed to list WAL directory: {process.stderr}"
        else:
            lines = process.stdout.strip().split('\n')
            # Skip first line (total) and get up to 20 most recent
            file_lines = [line for line in lines[1:21] if line.strip()]
            result['latest_files'] = file_lines
            result['wal_count'] = len(list(wal_dir.iterdir()))
            result['success'] = True
    
    except subprocess.TimeoutExpired:
        result['error'] = "WAL directory listing timed out"
    except Exception as e:
        result['error'] = f"Error checking WAL archive: {str(e)}"
    
    return result

