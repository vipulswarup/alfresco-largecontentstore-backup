"""S3 backup utilities using rclone."""

import os
import subprocess
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def check_rclone_installed() -> bool:
    """Check if rclone is installed and available."""
    try:
        result = subprocess.run(
            ['rclone', 'version'],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_rclone_env(access_key_id: str, secret_access_key: str, region: str) -> Dict[str, str]:
    """Get environment variables for rclone S3 operations."""
    env = os.environ.copy()
    env['AWS_ACCESS_KEY_ID'] = access_key_id
    env['AWS_SECRET_ACCESS_KEY'] = secret_access_key
    env['AWS_DEFAULT_REGION'] = region
    return env


def sync_to_s3(
    source_path: Path,
    s3_bucket: str,
    s3_path: str,
    access_key_id: str,
    secret_access_key: str,
    region: str,
    parallel_transfers: int = 4,
    timeout: Optional[int] = None
) -> Dict[str, Any]:
    """
    Sync local directory or file to S3 using rclone.
    
    Args:
        source_path: Local path to sync (file or directory)
        s3_bucket: S3 bucket name
        s3_path: Path within bucket (e.g., 'alfresco-backups/contentstore/')
        access_key_id: AWS access key ID
        secret_access_key: AWS secret access key
        region: AWS region
        parallel_transfers: Number of parallel transfers (default: 4)
        timeout: Timeout in seconds (optional)
    
    Returns:
        dict with keys: success, error, duration, files_transferred, bytes_transferred
    """
    import time
    from datetime import datetime
    
    start_time = time.time()
    result = {
        'success': False,
        'error': None,
        'duration': 0,
        'files_transferred': None,
        'bytes_transferred': None
    }
    
    # Check rclone is installed
    if not check_rclone_installed():
        result['error'] = "rclone is not installed. Please install rclone to use S3 backups."
        return result
    
    # Build S3 destination path
    s3_dest = f"s3:{s3_bucket}/{s3_path.rstrip('/')}/"
    
    # Build rclone command
    cmd = [
        'rclone',
        'sync',
        str(source_path),
        s3_dest,
        '--s3-provider', 'AWS',
        '--s3-region', region,
        '--transfers', str(parallel_transfers),
        '--checkers', str(parallel_transfers * 2),  # More checkers than transfers
        '--stats', '10s',  # Print stats every 10 seconds
        '--stats-one-line',  # One line stats
        '-v'  # Verbose for progress
    ]
    
    # Add timeout if specified
    if timeout:
        cmd.extend(['--timeout', f'{timeout}s'])
    
    logger.info(f"Syncing to S3: {source_path} -> {s3_dest}")
    logger.info(f"Using {parallel_transfers} parallel transfers")
    
    try:
        env = get_rclone_env(access_key_id, secret_access_key, region)
        process = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        duration = time.time() - start_time
        result['duration'] = duration
        
        if process.returncode == 0:
            result['success'] = True
            
            # Parse rclone stats from output
            output = process.stdout + process.stderr
            for line in output.split('\n'):
                if 'Transferred:' in line:
                    # Parse "Transferred:   123.456 k / 123.456 k, 100%, 1.234 MB/s, ETA 0s"
                    try:
                        parts = line.split('Transferred:')[1].split(',')[0].strip()
                        # Extract bytes (handle k, M, G suffixes)
                        if 'k' in parts.lower():
                            bytes_str = parts.split('k')[0].strip()
                            result['bytes_transferred'] = float(bytes_str) * 1024
                        elif 'M' in parts.upper():
                            bytes_str = parts.split('M')[0].strip()
                            result['bytes_transferred'] = float(bytes_str) * 1024 * 1024
                        elif 'G' in parts.upper():
                            bytes_str = parts.split('G')[0].strip()
                            result['bytes_transferred'] = float(bytes_str) * 1024 * 1024 * 1024
                    except (ValueError, IndexError):
                        pass
                elif 'Elapsed time:' in line:
                    # Already have duration, but could parse for verification
                    pass
        
        else:
            error_msg = process.stderr if process.stderr else process.stdout
            result['error'] = f"rclone sync failed with exit code {process.returncode}: {error_msg[:500]}"
            logger.error(result['error'])
    
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        result['duration'] = duration
        result['error'] = f"rclone sync timed out after {timeout} seconds"
        logger.error(result['error'])
    
    except Exception as e:
        duration = time.time() - start_time
        result['duration'] = duration
        result['error'] = f"Unexpected error during S3 sync: {str(e)}"
        logger.error(result['error'])
    
    return result


def copy_file_to_s3(
    source_file: Path,
    s3_bucket: str,
    s3_path: str,
    access_key_id: str,
    secret_access_key: str,
    region: str,
    timeout: Optional[int] = None
) -> Dict[str, Any]:
    """
    Copy a single file to S3 using rclone.
    
    Args:
        source_file: Local file to copy
        s3_bucket: S3 bucket name
        s3_path: Path within bucket (e.g., 'alfresco-backups/postgres/postgres-2025-11-06.sql.gz')
        access_key_id: AWS access key ID
        secret_access_key: AWS secret access key
        region: AWS region
        timeout: Timeout in seconds (optional)
    
    Returns:
        dict with keys: success, error, duration
    """
    import time
    
    start_time = time.time()
    result = {
        'success': False,
        'error': None,
        'duration': 0
    }
    
    # Check rclone is installed
    if not check_rclone_installed():
        result['error'] = "rclone is not installed. Please install rclone to use S3 backups."
        return result
    
    # Build S3 destination path
    s3_dest = f"s3:{s3_bucket}/{s3_path.lstrip('/')}"
    
    # Build rclone command
    cmd = [
        'rclone',
        'copy',
        str(source_file),
        s3_dest,
        '--s3-provider', 'AWS',
        '--s3-region', region,
        '-v'  # Verbose for progress
    ]
    
    # Add timeout if specified
    if timeout:
        cmd.extend(['--timeout', f'{timeout}s'])
    
    logger.info(f"Copying to S3: {source_file} -> {s3_dest}")
    
    try:
        env = get_rclone_env(access_key_id, secret_access_key, region)
        process = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        duration = time.time() - start_time
        result['duration'] = duration
        
        if process.returncode == 0:
            result['success'] = True
        else:
            error_msg = process.stderr if process.stderr else process.stdout
            result['error'] = f"rclone copy failed with exit code {process.returncode}: {error_msg[:500]}"
            logger.error(result['error'])
    
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        result['duration'] = duration
        result['error'] = f"rclone copy timed out after {timeout} seconds"
        logger.error(result['error'])
    
    except Exception as e:
        duration = time.time() - start_time
        result['duration'] = duration
        result['error'] = f"Unexpected error during S3 copy: {str(e)}"
        logger.error(result['error'])
    
    return result

