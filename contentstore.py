"""Contentstore backup using rsync with hardlink optimization."""

import subprocess
import time
from datetime import datetime
from pathlib import Path


def backup_contentstore(config):
    """
    Execute contentstore backup using rsync with hardlink strategy.
    
    Returns dict with keys: success, path, error, duration, start_time
    """
    start_time = datetime.now()
    date_str = start_time.strftime('%Y-%m-%d')
    
    contentstore_dir = config.backup_dir / 'contentstore'
    contentstore_dir.mkdir(parents=True, exist_ok=True)
    
    source = config.alf_base_dir / 'contentstore'
    destination = contentstore_dir / f'daily-{date_str}'
    last_link = contentstore_dir / 'last'
    
    result = {
        'success': False,
        'path': str(destination),
        'error': None,
        'duration': 0,
        'start_time': start_time.isoformat()
    }
    
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
    
    try:
        start = time.time()
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=28800  # 8 hour timeout for large contentstore
        )
        duration = time.time() - start
        
        if process.returncode != 0:
            result['error'] = f"rsync failed with exit code {process.returncode}\n"
            result['error'] += f"STDOUT: {process.stdout}\n"
            result['error'] += f"STDERR: {process.stderr}"
        else:
            # Update the 'last' symlink to point to current backup
            try:
                if last_link.exists() or last_link.is_symlink():
                    last_link.unlink()
                last_link.symlink_to(destination)
            except Exception as e:
                # Don't fail the whole backup if symlink update fails
                result['error'] = f"Warning: Could not update 'last' symlink: {str(e)}"
            
            result['success'] = True
            result['duration'] = duration
    
    except subprocess.TimeoutExpired:
        result['error'] = "rsync timed out after 8 hours"
    except FileNotFoundError:
        result['error'] = "rsync command not found. Ensure rsync is installed."
    except Exception as e:
        result['error'] = f"Unexpected error during contentstore backup: {str(e)}"
    
    return result

