"""Contentstore backup using rsync with hardlink optimization."""

import os
from datetime import datetime
from pathlib import Path
try:
    from alfresco_backup.utils.subprocess_utils import SubprocessRunner, validate_path
except ImportError:  # pragma: no cover
    from ..utils.subprocess_utils import SubprocessRunner, validate_path


def get_directory_size(path):
    """Calculate total size of directory in bytes."""
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.exists(filepath):
                    total_size += os.path.getsize(filepath)
    except Exception:
        pass
    return total_size


def backup_contentstore(config):
    """
    Execute contentstore backup using rsync with hardlink strategy.
    
    Returns dict with keys: success, path, error, duration, start_time, total_size_mb, additional_size_mb
    """
    start_time = datetime.now()
    timestamp_str = start_time.strftime('%Y-%m-%d_%H-%M-%S')
    
    contentstore_dir = config.backup_dir / 'contentstore'
    contentstore_dir.mkdir(parents=True, exist_ok=True)
    
    source = config.alf_base_dir / 'alf_data' / 'contentstore'
    destination = contentstore_dir / f'contentstore-{timestamp_str}'
    last_link = contentstore_dir / 'last'
    
    result = {
        'success': False,
        'path': str(destination),
        'error': None,
        'duration': 0,
        'start_time': start_time.isoformat(),
        'total_size_mb': 0,
        'additional_size_mb': 0
    }
    
    # Validate paths
    try:
        source = validate_path(source, must_exist=True)
        destination = validate_path(destination, must_exist=False)
    except ValueError as e:
        result['error'] = f"Invalid path: {e}"
        return result
    
    # Calculate size of previous backup if it exists (for fallback calculation)
    previous_backup_size = 0
    if last_link.exists() and last_link.is_symlink():
        try:
            previous_backup_path = last_link.resolve()
            if previous_backup_path.exists():
                previous_backup_size = get_directory_size(previous_backup_path)
        except Exception:
            pass
    
    # Build rsync command with stats output
    cmd = [
        'rsync',
        '-a',           # archive mode
        '--delete',     # delete files in dest that don't exist in source
        '--stats',      # print statistics
    ]
    
    # Add hardlink optimization if previous backup exists
    if last_link.exists() and last_link.is_symlink():
        cmd.extend(['--link-dest', str(last_link.resolve())])
    
    # Ensure source path has trailing slash
    cmd.extend([f'{source}/', f'{destination}/'])
    
    # Use common subprocess runner with configurable timeout
    timeout = getattr(config, 'contentstore_timeout', 86400)  # Default 24 hours
    runner = SubprocessRunner(timeout=timeout)
    subprocess_result = runner.run_command(cmd)
    
    if subprocess_result['success']:
        # Calculate backup sizes
        if destination.exists():
            total_size = get_directory_size(destination)
            result['total_size_mb'] = total_size / (1024 * 1024)
            
            # Parse rsync stats to get actual transferred size
            # Look for "Total transferred file size" in rsync output
            additional_size = 0
            if subprocess_result.get('stdout'):
                output = subprocess_result['stdout']
                for line in output.split('\n'):
                    if 'Total transferred file size:' in line:
                        try:
                            # Extract size from line like "Total transferred file size: 1,234,567 bytes"
                            size_str = line.split('Total transferred file size:')[1].split('bytes')[0].strip().replace(',', '')
                            additional_size = int(size_str)
                            break
                        except (ValueError, IndexError):
                            pass
            
            # If we couldn't parse rsync stats, use a fallback calculation
            if additional_size == 0:
                # Estimate: difference between current and previous backup sizes
                # This is an approximation - actual disk usage is less due to hardlinks
                additional_size = max(0, total_size - previous_backup_size)
            
            result['additional_size_mb'] = additional_size / (1024 * 1024)
        
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

