"""WAL archive monitoring."""

from pathlib import Path
from alfresco_backup.utils.subprocess_utils import SubprocessRunner, validate_path


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
    
    # Validate WAL directory
    try:
        wal_dir = validate_path(wal_dir, must_exist=True)
    except ValueError as e:
        result['error'] = f"Invalid WAL directory: {e}"
        return result
    
    try:
        # List WAL files
        cmd = ['ls', '-lht', str(wal_dir)]
        runner = SubprocessRunner(timeout=30)
        subprocess_result = runner.run_command(cmd)
        
        if subprocess_result['success']:
            lines = subprocess_result['stdout'].strip().split('\n')
            # Skip first line (total) and get up to 20 most recent
            file_lines = [line for line in lines[1:21] if line.strip()]
            result['latest_files'] = file_lines
            result['wal_count'] = len(list(wal_dir.iterdir()))
            result['success'] = True
        else:
            result['error'] = subprocess_result['error']
    
    except Exception as e:
        result['error'] = f"Error checking WAL archive: {str(e)}"
    
    return result

