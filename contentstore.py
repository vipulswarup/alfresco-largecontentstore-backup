"""Contentstore backup using rsync with hardlink optimization."""

from datetime import datetime
from pathlib import Path
from subprocess_utils import SubprocessRunner, validate_path


def backup_contentstore(config):
    """
    Execute contentstore backup using rsync with hardlink strategy.
    
    Returns dict with keys: success, path, error, duration, start_time
    """
    start_time = datetime.now()
    date_str = start_time.strftime('%Y-%m-%d')
    
    contentstore_dir = config.backup_dir / 'contentstore'
    contentstore_dir.mkdir(parents=True, exist_ok=True)
    
    source = config.alf_base_dir / 'alf_data' / 'contentstore'
    destination = contentstore_dir / f'daily-{date_str}'
    last_link = contentstore_dir / 'last'
    
    result = {
        'success': False,
        'path': str(destination),
        'error': None,
        'duration': 0,
        'start_time': start_time.isoformat()
    }
    
    # Validate paths
    try:
        source = validate_path(source, must_exist=True)
        destination = validate_path(destination, must_exist=False)
    except ValueError as e:
        result['error'] = f"Invalid path: {e}"
        return result
    
    # Build rsync command
    cmd = [
        'rsync',
        '-a',           # archive mode
        '--delete',     # delete files in dest that don't exist in source
    ]
    
    # Add hardlink optimization if previous backup exists
    if last_link.exists() and last_link.is_symlink():
        cmd.extend(['--link-dest', str(last_link.resolve())])
    
    # Ensure source path has trailing slash
    cmd.extend([f'{source}/', f'{destination}/'])
    
    # Use common subprocess runner
    runner = SubprocessRunner(timeout=28800)  # 8 hour timeout for large contentstore
    subprocess_result = runner.run_command(cmd)
    
    if subprocess_result['success']:
        # Update the 'last' symlink to point to current backup
        try:
            if last_link.exists() or last_link.is_symlink():
                last_link.unlink()
            last_link.symlink_to(destination)
        except Exception as e:
            # Don't fail the whole backup if symlink update fails
            result['error'] = f"Warning: Could not update 'last' symlink: {str(e)}"
        
        result['success'] = True
        result['duration'] = subprocess_result['duration']
    else:
        result['error'] = subprocess_result['error']
    
    return result

