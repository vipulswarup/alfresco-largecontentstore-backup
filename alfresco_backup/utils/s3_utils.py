"""S3 backup utilities using rclone."""

import os
import subprocess
import logging
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

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
    
    # Build rclone command - use env auth with environment variables
    cmd = [
        'rclone',
        'sync',
        str(source_path),
        s3_dest,
        '--s3-provider', 'AWS',
        '--s3-region', region,
        '--s3-env-auth', 'true',  # Use environment variables for auth
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
    
    # Build rclone command - use env auth with environment variables
    cmd = [
        'rclone',
        'copy',
        str(source_file),
        s3_dest,
        '--s3-provider', 'AWS',
        '--s3-region', region,
        '--s3-env-auth', 'true',  # Use environment variables for auth
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


def check_s3_versioning_enabled(
    s3_bucket: str,
    access_key_id: str,
    secret_access_key: str,
    region: str
) -> bool:
    """
    Check if S3 bucket versioning is enabled by attempting to list versions.
    
    Args:
        s3_bucket: S3 bucket name
        access_key_id: AWS access key ID
        secret_access_key: AWS secret access key
        region: AWS region
    
    Returns:
        True if versioning is enabled (can list versions), False otherwise
    """
    if not check_rclone_installed():
        return False
    
    try:
        env = get_rclone_env(access_key_id, secret_access_key, region)
        s3_path = f"s3:{s3_bucket}/alfresco-backups/"
        cmd = [
            'rclone',
            'lsjson',
            '--versions',
            '--s3-provider', 'AWS',
            '--s3-region', region,
            '--s3-env-auth', 'true',  # Use environment variables for auth
            s3_path
        ]
        
        process = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if process.returncode == 0:
            import json
            try:
                data = json.loads(process.stdout)
                for item in data:
                    if 'VersionID' in item:
                        return True
            except json.JSONDecodeError:
                pass
        
        return False
    
    except Exception as e:
        logger.warning(f"Could not check S3 versioning status: {e}")
        return False


def enable_s3_versioning(
    s3_bucket: str,
    access_key_id: str,
    secret_access_key: str,
    region: str
) -> Dict[str, Any]:
    """
    Enable versioning on S3 bucket using AWS CLI if available.
    
    Args:
        s3_bucket: S3 bucket name
        access_key_id: AWS access key ID
        secret_access_key: AWS secret access key
        region: AWS region
    
    Returns:
        dict with keys: success, error
    """
    result = {
        'success': False,
        'error': None
    }
    
    try:
        env = os.environ.copy()
        env['AWS_ACCESS_KEY_ID'] = access_key_id
        env['AWS_SECRET_ACCESS_KEY'] = secret_access_key
        env['AWS_DEFAULT_REGION'] = region
        
        cmd = [
            'aws',
            's3api',
            'put-bucket-versioning',
            '--bucket', s3_bucket,
            '--versioning-configuration', 'Status=Enabled'
        ]
        
        process = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if process.returncode == 0:
            result['success'] = True
            logger.info(f"S3 versioning enabled on bucket: {s3_bucket}")
        else:
            error_msg = process.stderr if process.stderr else process.stdout
            result['error'] = f"AWS CLI not available or failed: {error_msg[:500]}"
            logger.warning(result['error'])
            logger.warning("Please enable S3 versioning manually via AWS Console or CLI")
            result['error'] = "AWS CLI not available. Please enable S3 versioning manually."
    
    except FileNotFoundError:
        result['error'] = "AWS CLI not installed. Please install AWS CLI or enable S3 versioning manually via AWS Console."
        logger.warning(result['error'])
    except Exception as e:
        result['error'] = f"Error enabling S3 versioning: {str(e)}"
        logger.error(result['error'])
    
    return result


def list_s3_postgres_backups(
    s3_bucket: str,
    access_key_id: str,
    secret_access_key: str,
    region: str
) -> List[str]:
    """
    List PostgreSQL backups in S3 with timestamps.
    
    Args:
        s3_bucket: S3 bucket name
        access_key_id: AWS access key ID
        secret_access_key: AWS secret access key
        region: AWS region
    
    Returns:
        List of timestamp strings (YYYY-MM-DD_HH-MM-SS format)
    """
    if not check_rclone_installed():
        return []
    
    backups = []
    s3_path = f"s3:{s3_bucket}/alfresco-backups/postgres/"
    
    try:
        env = get_rclone_env(access_key_id, secret_access_key, region)
        cmd = [
            'rclone',
            'lsf',
            '--format', 'p',
            '--s3-provider', 'AWS',
            '--s3-region', region,
            '--s3-env-auth', 'true',  # Use environment variables for auth
            s3_path
        ]
        
        process = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if process.returncode == 0:
            for line in process.stdout.split('\n'):
                line = line.strip()
                if line and line.startswith('postgres-') and line.endswith('.sql.gz'):
                    timestamp = line.replace('postgres-', '').replace('.sql.gz', '')
                    try:
                        datetime.strptime(timestamp, '%Y-%m-%d_%H-%M-%S')
                        backups.append(timestamp)
                    except ValueError:
                        continue
        
        return sorted(backups, reverse=True)
    
    except Exception as e:
        logger.error(f"Error listing S3 PostgreSQL backups: {e}")
        return []


def list_s3_contentstore_versions(
    s3_bucket: str,
    access_key_id: str,
    secret_access_key: str,
    region: str
) -> List[Dict[str, Any]]:
    """
    List contentstore versions in S3 with timestamps.
    
    Args:
        s3_bucket: S3 bucket name
        access_key_id: AWS access key ID
        secret_access_key: AWS secret access key
        region: AWS region
    
    Returns:
        List of dicts with keys: version_id, timestamp, is_latest
    """
    if not check_rclone_installed():
        return []
    
    versions = []
    s3_path = f"s3:{s3_bucket}/alfresco-backups/contentstore/"
    
    try:
        env = get_rclone_env(access_key_id, secret_access_key, region)
        cmd = [
            'rclone',
            'lsjson',
            '--versions',
            '--s3-provider', 'AWS',
            '--s3-region', region,
            '--s3-env-auth', 'true',  # Use environment variables for auth
            s3_path
        ]
        
        process = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if process.returncode == 0:
            import json
            try:
                data = json.loads(process.stdout)
                for item in data:
                    if 'ModTime' in item and 'VersionID' in item:
                        versions.append({
                            'version_id': item['VersionID'],
                            'timestamp': datetime.fromisoformat(item['ModTime'].replace('Z', '+00:00')),
                            'is_latest': item.get('IsLatest', False)
                        })
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"Could not parse S3 version list: {e}")
        
        return sorted(versions, key=lambda x: x['timestamp'], reverse=True)
    
    except Exception as e:
        logger.error(f"Error listing S3 contentstore versions: {e}")
        return []


def get_s3_version_by_date(
    s3_bucket: str,
    access_key_id: str,
    secret_access_key: str,
    region: str,
    target_date: datetime
) -> Optional[str]:
    """
    Get version ID for contentstore at or before target date.
    
    Args:
        s3_bucket: S3 bucket name
        access_key_id: AWS access key ID
        secret_access_key: AWS secret access key
        region: AWS region
        target_date: Target datetime for restore
    
    Returns:
        Version ID string or None if no version found
    """
    versions = list_s3_contentstore_versions(s3_bucket, access_key_id, secret_access_key, region)
    
    for version in versions:
        if version['timestamp'] <= target_date:
            return version['version_id']
    
    return None


def download_from_s3(
    s3_bucket: str,
    s3_path: str,
    local_path: Path,
    access_key_id: str,
    secret_access_key: str,
    region: str,
    version_id: Optional[str] = None,
    timeout: Optional[int] = None
) -> Dict[str, Any]:
    """
    Download file or directory from S3 to local path.
    
    Args:
        s3_bucket: S3 bucket name
        s3_path: Path within bucket
        local_path: Local destination path
        access_key_id: AWS access key ID
        secret_access_key: AWS secret access key
        region: AWS region
        version_id: Optional version ID for versioned objects
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
    
    if not check_rclone_installed():
        result['error'] = "rclone is not installed. Please install rclone to use S3 restore."
        return result
    
    s3_source = f"s3:{s3_bucket}/{s3_path.lstrip('/')}"
    if version_id:
        s3_source = f"{s3_source}?versionId={version_id}"
    
    local_path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        'rclone',
        'copy',
        s3_source,
        str(local_path),
        '--s3-provider', 'AWS',
        '--s3-region', region,
        '--s3-env-auth', 'true',  # Use environment variables for auth
        '-v'
    ]
    
    if timeout:
        cmd.extend(['--timeout', f'{timeout}s'])
    
    logger.info(f"Downloading from S3: {s3_source} -> {local_path}")
    
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
            result['error'] = f"rclone download failed with exit code {process.returncode}: {error_msg[:500]}"
            logger.error(result['error'])
    
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        result['duration'] = duration
        result['error'] = f"rclone download timed out after {timeout} seconds"
        logger.error(result['error'])
    
    except Exception as e:
        duration = time.time() - start_time
        result['duration'] = duration
        result['error'] = f"Unexpected error during S3 download: {str(e)}"
        logger.error(result['error'])
    
    return result

