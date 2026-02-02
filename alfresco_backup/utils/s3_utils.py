"""S3 backup utilities using rclone."""

import os
import subprocess
import logging
import tempfile
import re
import json
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
    """Get environment variables for rclone S3 operations.
    
    Uses RCLONE_CONFIG_S3_* environment variables to create a temporary 's3' remote
    without needing a config file.
    """
    env = os.environ.copy()
    # Set rclone config via environment variables (creates temporary 's3' remote)
    env['RCLONE_CONFIG_S3_TYPE'] = 's3'
    env['RCLONE_CONFIG_S3_PROVIDER'] = 'AWS'
    env['RCLONE_CONFIG_S3_ACCESS_KEY_ID'] = access_key_id
    env['RCLONE_CONFIG_S3_SECRET_ACCESS_KEY'] = secret_access_key
    env['RCLONE_CONFIG_S3_REGION'] = region
    env['RCLONE_CONFIG_S3_ENV_AUTH'] = 'false'  # Use explicit credentials, not env vars
    return env


def get_s3_folder_size(
    s3_bucket: str,
    s3_path: str,
    access_key_id: str,
    secret_access_key: str,
    region: str,
    timeout: Optional[int] = 300
) -> Optional[int]:
    """
    Get the total size in bytes of a folder in S3 using rclone size command.
    
    Args:
        s3_bucket: S3 bucket name
        s3_path: Path within bucket (e.g., 'alfresco-backups/contentstore/')
        access_key_id: AWS access key ID
        secret_access_key: AWS secret access key
        region: AWS region
        timeout: Timeout in seconds (default: 300)
    
    Returns:
        Total size in bytes, or None if error occurs
    """
    if not check_rclone_installed():
        logger.warning("rclone is not installed. Cannot get S3 folder size.")
        return None
    
    # Build S3 path - 's3' remote is created via RCLONE_CONFIG_S3_* env vars
    s3_full_path = f"s3:{s3_bucket}/{s3_path.rstrip('/')}/"
    
    # Build rclone size command
    cmd = [
        'rclone',
        'size',
        s3_full_path,
        '--json'  # JSON output for easier parsing
    ]
    
    try:
        env = get_rclone_env(access_key_id, secret_access_key, region)
        process = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if process.returncode == 0:
            try:
                data = json.loads(process.stdout)
                # rclone size --json returns: {"count": N, "bytes": M, "sizestring": "..."}
                size_bytes = data.get('bytes', 0)
                logger.debug(f"S3 folder size for {s3_full_path}: {size_bytes} bytes ({size_bytes / (1024*1024):.2f} MB)")
                return int(size_bytes)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"Could not parse rclone size JSON output: {e}")
                return None
        else:
            # If folder doesn't exist yet (first backup), rclone returns non-zero
            # This is expected and not an error
            if "directory not found" in process.stderr.lower() or "couldn't find" in process.stderr.lower():
                logger.debug(f"S3 folder {s3_full_path} does not exist yet (first backup)")
                return 0
            logger.warning(f"rclone size failed: {process.stderr[:200]}")
            return None
    
    except subprocess.TimeoutExpired:
        logger.warning(f"rclone size timed out after {timeout} seconds")
        return None
    except Exception as e:
        logger.warning(f"Error getting S3 folder size: {str(e)}")
        return None


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
    
    # Build S3 destination path - 's3' remote is created via RCLONE_CONFIG_S3_* env vars
    s3_dest = f"s3:{s3_bucket}/{s3_path.rstrip('/')}/"
    
    # Build rclone command
    cmd = [
        'rclone',
        'sync',
        str(source_path),
        s3_dest,
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
            # rclone outputs stats in format like:
            # "Transferred: 1.234 GiB / 5.678 GiB, 22%, 12.34 MiB/s, ETA 6m32s"
            # or "Transferred:   123.456 k / 123.456 k, 100%, 1.234 MB/s, ETA 0s"
            # We need the first number (actual transferred amount) before the "/"
            output = process.stdout + process.stderr
            last_transferred_value = None
            transferred_lines = []
            
            for line in output.split('\n'):
                if 'Transferred:' in line:
                    transferred_lines.append(line)
                    try:
                        # Extract the part after "Transferred:"
                        transferred_part = line.split('Transferred:')[1].strip()
                        # Get the first number and unit (before "/" if present, or before ",")
                        if '/' in transferred_part:
                            amount_str = transferred_part.split('/')[0].strip()
                        else:
                            amount_str = transferred_part.split(',')[0].strip()
                        
                        # Parse the number and unit
                        # Handle formats like "1.234 GiB", "123.456 k", "5.678 M", etc.
                        amount_str = amount_str.strip()
                        if not amount_str:
                            continue
                            
                        # Extract numeric part and unit
                        # Match formats like "1.234 GiB", "123.456 k", "5.678 MB", etc.
                        # Pattern: number followed by optional space and unit (K/M/G/T with optional i and/or B)
                        # Also handle cases where there's no space: "1.234GiB"
                        match = re.match(r'([\d.]+)\s*([KMGTkmgt][iI]?[bB]?)', amount_str)
                        if not match:
                            # Try without space
                            match = re.match(r'([\d.]+)([KMGTkmgt][iI]?[bB]?)', amount_str)
                        
                        if match:
                            number = float(match.group(1))
                            unit = match.group(2).upper()
                            
                            # Determine if binary (i present) or decimal unit
                            is_binary = 'I' in unit
                            base_unit = unit[0] if unit else ''
                            
                            # Convert to bytes based on unit
                            if base_unit == 'K':
                                multiplier = 1024 if is_binary else 1000
                                bytes_value = number * multiplier
                            elif base_unit == 'M':
                                multiplier = 1024 * 1024 if is_binary else 1000 * 1000
                                bytes_value = number * multiplier
                            elif base_unit == 'G':
                                multiplier = 1024 * 1024 * 1024 if is_binary else 1000 * 1000 * 1000
                                bytes_value = number * multiplier
                            elif base_unit == 'T':
                                multiplier = 1024 * 1024 * 1024 * 1024 if is_binary else 1000 * 1000 * 1000 * 1000
                                bytes_value = number * multiplier
                            else:
                                # Fallback: assume bytes if unknown unit
                                bytes_value = number
                            
                            last_transferred_value = int(bytes_value)
                            logger.debug(f"Parsed '{amount_str}' as {last_transferred_value} bytes")
                    except (ValueError, IndexError, AttributeError) as e:
                        logger.debug(f"Could not parse Transferred line: {line[:100]}, error: {e}")
                        pass
            
            # Use the last (final) transferred value
            if last_transferred_value is not None:
                result['bytes_transferred'] = last_transferred_value
                logger.info(f"Parsed bytes_transferred from rclone output: {last_transferred_value / (1024*1024):.2f} MB")
            else:
                logger.warning("Could not parse bytes_transferred from rclone output. Output may be in unexpected format.")
                # Log transferred lines for debugging
                if transferred_lines:
                    logger.info(f"Found {len(transferred_lines)} 'Transferred:' lines. Sample (last 3):")
                    for line in transferred_lines[-3:]:
                        logger.info(f"  {line[:200]}")
                else:
                    logger.info("No 'Transferred:' lines found in rclone output.")
                    # Log a sample of the output for debugging (last 1000 chars)
                    output_sample = (process.stdout + process.stderr)[-1000:] if (process.stdout + process.stderr) else "No output"
                    logger.info(f"Last 1000 chars of rclone output: {output_sample}")
        
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
    
    # Build S3 destination path - 's3' remote is created via RCLONE_CONFIG_S3_* env vars
    s3_dest = f"s3:{s3_bucket}/{s3_path.lstrip('/')}"
    
    # Build rclone command
    cmd = [
        'rclone',
        'copy',
        str(source_file),
        s3_dest,
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
        # Build S3 path - 's3' remote is created via RCLONE_CONFIG_S3_* env vars
        s3_path = f"s3:{s3_bucket}/alfresco-backups/"
        cmd = [
            'rclone',
            'lsjson',
            '--versions',
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
    # Build S3 path - 's3' remote is created via RCLONE_CONFIG_S3_* env vars
    s3_path = f"s3:{s3_bucket}/alfresco-backups/postgres/"
    
    try:
        env = get_rclone_env(access_key_id, secret_access_key, region)
        
        # Try recursive listing first to find actual files
        # rclone lsf with -R lists recursively and shows full paths
        cmd = [
            'rclone',
            'lsf',
            '-R',
            '--format', 'p',
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
            if process.stdout.strip():
                logger.debug(f"rclone lsf -R output: {process.stdout[:500]}")
            for line in process.stdout.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # Handle both file paths and folder names
                # Files: alfresco-backups/postgres/postgres-2026-02-02_02-00-01.sql.gz
                # Folders/prefixes: postgres-2026-02-02_02-00-01.sql.gz/ or postgres-2026-02-02_02-00-01.sql.gz
                filename = line.split('/')[-1]  # Get last component
                if filename.startswith('postgres-') and filename.endswith('.sql.gz'):
                    # Remove trailing slash if present (folder/prefix)
                    filename = filename.rstrip('/')
                    timestamp = filename.replace('postgres-', '').replace('.sql.gz', '')
                    try:
                        datetime.strptime(timestamp, '%Y-%m-%d_%H-%M-%S')
                        if timestamp not in backups:
                            backups.append(timestamp)
                    except ValueError:
                        continue
        else:
            logger.warning(f"rclone lsf -R failed: {process.stderr[:200]}")
        
        # If no backups found with recursive, try non-recursive (in case files are direct children)
        if not backups:
            cmd = [
                'rclone',
                'lsf',
                '--format', 'p',
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
                if process.stdout.strip():
                    logger.debug(f"rclone lsf output: {process.stdout[:500]}")
                for line in process.stdout.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Remove trailing slash if present
                    filename = line.rstrip('/')
                    if filename.startswith('postgres-') and filename.endswith('.sql.gz'):
                        timestamp = filename.replace('postgres-', '').replace('.sql.gz', '')
                        try:
                            datetime.strptime(timestamp, '%Y-%m-%d_%H-%M-%S')
                            if timestamp not in backups:
                                backups.append(timestamp)
                        except ValueError:
                            continue
            else:
                logger.warning(f"rclone lsf failed: {process.stderr[:200]}")
        
        # If still no backups, try rclone ls (shows files with sizes, filters out empty prefixes)
        if not backups:
            cmd = [
                'rclone',
                'ls',
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
                if process.stdout.strip():
                    logger.debug(f"rclone ls output: {process.stdout[:500]}")
                for line in process.stdout.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    
                    # rclone ls format: size path
                    # Example: 1234567 alfresco-backups/postgres/postgres-2026-02-02_02-00-01.sql.gz
                    parts = line.split(None, 1)  # Split on whitespace, max 1 split
                    if len(parts) == 2:
                        file_path = parts[1]
                        filename = file_path.split('/')[-1]
                        if filename.startswith('postgres-') and filename.endswith('.sql.gz'):
                            timestamp = filename.replace('postgres-', '').replace('.sql.gz', '')
                            try:
                                datetime.strptime(timestamp, '%Y-%m-%d_%H-%M-%S')
                                if timestamp not in backups:
                                    backups.append(timestamp)
                            except ValueError:
                                continue
        
        if backups:
            logger.info(f"Found {len(backups)} PostgreSQL backups in S3")
        else:
            logger.warning(f"No PostgreSQL backups found in S3 at {s3_path}")
            # Log the last command's output for debugging
            if 'process' in locals() and process.returncode != 0:
                logger.warning(f"Last rclone command failed: stdout={process.stdout[:500]}, stderr={process.stderr[:500]}")
        
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
    # Build S3 path - 's3' remote is created via RCLONE_CONFIG_S3_* env vars
    s3_path = f"s3:{s3_bucket}/alfresco-backups/contentstore/"
    
    try:
        env = get_rclone_env(access_key_id, secret_access_key, region)
        cmd = [
            'rclone',
            'lsjson',
            '--versions',
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


def restore_contentstore_from_s3_version(
    s3_bucket: str,
    s3_path: str,
    local_path: Path,
    access_key_id: str,
    secret_access_key: str,
    region: str,
    target_timestamp: datetime,
    timeout: Optional[int] = None
) -> Dict[str, Any]:
    """
    Restore contentstore from S3 using versioning to restore files to their state at target timestamp.
    
    Uses rclone with --s3-version-at to restore each file to its version at the target time.
    This enables point-in-time recovery by restoring files that were deleted after the target time.
    
    Args:
        s3_bucket: S3 bucket name
        s3_path: Path within bucket (e.g., 'alfresco-backups/contentstore/')
        local_path: Local destination path
        access_key_id: AWS access key ID
        secret_access_key: AWS secret access key
        region: AWS region
        target_timestamp: Target datetime to restore to (files will be restored to versions at or before this time)
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
    
    # Build S3 source path - 's3' remote is created via RCLONE_CONFIG_S3_* env vars
    s3_source = f"s3:{s3_bucket}/{s3_path.rstrip('/')}/"
    
    local_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Format timestamp for rclone --s3-version-at (RFC3339 format: 2006-01-02T15:04:05Z)
    version_at_str = target_timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    # Use rclone copy with --s3-version-at to restore files to their versions at target time
    cmd = [
        'rclone',
        'copy',
        s3_source,
        str(local_path),
        '--s3-version-at', version_at_str,
        '--transfers', '4',
        '--checkers', '8',
        '-v'
    ]
    
    if timeout:
        cmd.extend(['--timeout', f'{timeout}s'])
    
    logger.info(f"Restoring contentstore from S3 to timestamp {version_at_str}: {s3_source} -> {local_path}")
    
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
            result['error'] = f"rclone restore failed with exit code {process.returncode}: {error_msg[:500]}"
            logger.error(result['error'])
    
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        result['duration'] = duration
        result['error'] = f"rclone restore timed out after {timeout} seconds"
        logger.error(result['error'])
    
    except Exception as e:
        duration = time.time() - start_time
        result['duration'] = duration
        result['error'] = f"Unexpected error during S3 restore: {str(e)}"
        logger.error(result['error'])
    
    return result


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
    
    # Build S3 source path - 's3' remote is created via RCLONE_CONFIG_S3_* env vars
    s3_source = f"s3:{s3_bucket}/{s3_path.lstrip('/')}"
    if version_id:
        # For versioned objects, use --s3-version-at flag
        # Note: rclone doesn't support direct version ID in path, need to use flag or list versions
        logger.warning(f"Version ID {version_id} specified but rclone copy doesn't support direct version ID access")
        logger.warning("Will attempt to download latest version - version-specific restore may need manual intervention")
    
    local_path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        'rclone',
        'copy',
        s3_source,
        str(local_path),
        '-v'
    ]
    
    # If version ID is specified, we'd need to use --s3-version-at, but that requires a timestamp
    # For now, we'll download the latest version
    # TODO: Implement proper version ID handling if needed
    
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

