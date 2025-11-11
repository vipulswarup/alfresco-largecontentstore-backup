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


def cleanup_failed_backups(contentstore_dir, last_link):
    """
    Clean up incomplete/failed backup attempts to free disk space.
    A backup is considered failed if it's not the current 'last' symlink target.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not last_link.exists() or not last_link.is_symlink():
        return  # No successful backup yet
    
    try:
        last_backup = last_link.resolve()
        
        # Find all contentstore-* directories
        for item in contentstore_dir.iterdir():
            if item.is_dir() and item.name.startswith('contentstore-'):
                # Skip if this is the last successful backup
                if item.resolve() == last_backup:
                    continue
                
                # Check if this is a recent directory (within last 24 hours)
                # to avoid deleting backups that should be kept by retention policy
                try:
                    timestamp_str = item.name.replace('contentstore-', '')
                    from datetime import datetime, timedelta
                    backup_time = datetime.strptime(timestamp_str, '%Y-%m-%d_%H-%M-%S')
                    age_hours = (datetime.now() - backup_time).total_seconds() / 3600
                    
                    # Only clean up very recent failed attempts (< 12 hours old)
                    # Older backups will be handled by retention policy
                    if age_hours < 12:
                        logger.warning(f"Cleaning up recent failed backup attempt: {item.name}")
                        import shutil
                        shutil.rmtree(item)
                        logger.info(f"Removed incomplete backup: {item.name}")
                except (ValueError, Exception) as e:
                    logger.warning(f"Could not process {item.name}: {e}")
    except Exception as e:
        logger.error(f"Error during failed backup cleanup: {e}")


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
    
    # Clean up any recent failed backup attempts first
    cleanup_failed_backups(contentstore_dir, last_link)
    
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
    
    # Check available disk space before starting
    import shutil
    disk_stat = shutil.disk_usage(contentstore_dir)
    available_gb = disk_stat.free / (1024**3)
    source_size = get_directory_size(source)
    source_gb = source_size / (1024**3)
    
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Disk space check: {available_gb:.1f} GB available, source is {source_gb:.1f} GB")
    
    # Warn if less than 20% of source size is available
    # (rsync with hardlinks typically uses much less, but we need buffer for new/changed files)
    if available_gb < (source_gb * 0.2):
        logger.warning(f"Low disk space: only {available_gb:.1f} GB available for {source_gb:.1f} GB source")
        logger.warning("Consider cleaning up old backups or using a larger disk")
    
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
    result['timeout_seconds'] = timeout
    runner = SubprocessRunner(timeout=timeout)
    
    logger.info(f"Executing rsync command (timeout: {timeout/3600:.1f} hours)...")
    logger.info(f"  Command: {' '.join(cmd[:5])}... [truncated]")
    
    subprocess_result = runner.run_command(cmd)
    
    # Parse rsync stats for progress information (even on failure)
    files_transferred = None
    bytes_transferred = None
    if subprocess_result.get('stdout'):
        output = subprocess_result['stdout']
        for line in output.split('\n'):
            # Parse "Number of files: X (reg: Y, dir: Z)"
            if 'Number of files:' in line:
                try:
                    # Extract total files
                    parts = line.split('Number of files:')[1].split('(')[0].strip()
                    files_transferred = int(parts.replace(',', ''))
                except (ValueError, IndexError):
                    pass
            # Parse "Total transferred file size: X bytes"
            if 'Total transferred file size:' in line:
                try:
                    size_str = line.split('Total transferred file size:')[1].split('bytes')[0].strip().replace(',', '')
                    bytes_transferred = int(size_str)
                except (ValueError, IndexError):
                    pass
    
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
        
        # Store files transferred info
        if files_transferred is not None:
            result['files_transferred'] = files_transferred
            logger.info(f"Files processed: {files_transferred:,}")
        
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
        # Failure case - capture partial results
        result['error'] = subprocess_result['error']
        result['duration'] = subprocess_result.get('duration', 0)
        
        # Check if destination exists (partial backup)
        if destination.exists():
            try:
                partial_size = get_directory_size(destination)
                result['partial_size_mb'] = partial_size / (1024 * 1024)
                logger.warning(f"Partial backup detected: {result['partial_size_mb']:.2f} MB ({result['partial_size_mb']/1024:.2f} GB)")
            except Exception:
                pass
        
        # Store progress information
        if files_transferred is not None:
            result['files_transferred'] = files_transferred
            logger.warning(f"Files transferred before failure: {files_transferred:,}")
        
        if bytes_transferred is not None:
            result['bytes_transferred'] = bytes_transferred
            bytes_mb = bytes_transferred / (1024 * 1024)
            logger.warning(f"Data transferred before failure: {bytes_mb:.2f} MB ({bytes_mb/1024:.2f} GB)")
        
        # Include timeout information if it was a timeout
        if subprocess_result.get('timeout_seconds'):
            result['timeout_seconds'] = subprocess_result['timeout_seconds']
            result['elapsed_before_timeout'] = subprocess_result.get('elapsed_before_timeout', 0)
            logger.error(f"Operation timed out after {subprocess_result.get('elapsed_before_timeout', 0)/3600:.2f} hours (limit: {subprocess_result['timeout_seconds']/3600:.2f} hours)")
        
        # Include stderr/stdout if available for debugging
        if subprocess_result.get('stderr'):
            result['stderr'] = subprocess_result['stderr']
        if subprocess_result.get('stdout'):
            result['stdout'] = subprocess_result['stdout']
    
    return result

