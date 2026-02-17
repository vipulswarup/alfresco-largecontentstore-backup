#!/usr/bin/env python3
"""
Manual cleanup script for Alfresco backups.
Use this to free up disk space by removing old or failed backup attempts.
Features multithreaded deletion for faster cleanup of large backups.
Supports both local backups and S3 backups.
"""

import os
import sys
import shutil
import threading
import time
import subprocess
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue

class ProgressTracker:
    """Thread-safe progress tracker for deletion operations."""
    
    def __init__(self, total_items):
        self.total_items = total_items
        self.completed = 0
        self.failed = 0
        self.lock = threading.Lock()
        self.start_time = time.time()
    
    def increment(self, success=True):
        with self.lock:
            self.completed += 1
            if not success:
                self.failed += 1
    
    def get_progress(self):
        with self.lock:
            elapsed = time.time() - self.start_time
            percent = (self.completed / self.total_items * 100) if self.total_items > 0 else 0
            return {
                'completed': self.completed,
                'total': self.total_items,
                'failed': self.failed,
                'percent': percent,
                'elapsed': elapsed
            }
    
    def print_progress(self):
        stats = self.get_progress()
        percent = stats['percent']
        elapsed = stats['elapsed']
        
        # Calculate ETA
        if stats['completed'] > 0:
            rate = stats['completed'] / elapsed
            remaining = stats['total'] - stats['completed']
            eta_seconds = remaining / rate if rate > 0 else 0
            eta_min = int(eta_seconds / 60)
            eta_sec = int(eta_seconds % 60)
            eta_str = f"{eta_min}m {eta_sec}s"
        else:
            eta_str = "calculating..."
        
        elapsed_min = int(elapsed / 60)
        elapsed_sec = int(elapsed % 60)
        
        print(f"\rProgress: {stats['completed']}/{stats['total']} ({percent:.1f}%) "
              f"| Failed: {stats['failed']} | Elapsed: {elapsed_min}m {elapsed_sec}s | ETA: {eta_str}", 
              end='', flush=True)


def get_directory_size(path):
    """Calculate total size of directory in GB."""
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.exists(filepath):
                    total_size += os.path.getsize(filepath)
    except Exception as e:
        print(f"  Error calculating size: {e}")
    return total_size / (1024**3)  # Convert to GB


def collect_deletion_chunks(root_path, max_depth=2):
    """
    Collect subdirectories at specified depth for parallel deletion.
    
    Args:
        root_path: Root directory to scan
        max_depth: Depth at which to stop and collect directories (1=year, 2=month, 3=day)
    
    Returns:
        List of Path objects representing chunks to delete in parallel
    """
    chunks = []
    root_path = Path(root_path)
    
    try:
        for root, dirs, files in os.walk(root_path):
            depth = str(root).replace(str(root_path), '').count(os.sep)
            
            if depth == max_depth:
                # Add each subdirectory at this depth as a chunk
                for d in dirs:
                    chunks.append(Path(root) / d)
                # Don't recurse deeper (optimization)
                dirs.clear()
            elif depth > max_depth:
                # Shouldn't reach here, but safety check
                break
        
        # If we didn't find enough chunks, fall back to shallower depth
        if len(chunks) < 5 and max_depth > 1:
            return collect_deletion_chunks(root_path, max_depth - 1)
        
        # If still no chunks, return the root itself
        if not chunks:
            chunks = [root_path]
    
    except Exception as e:
        print(f"  Warning: Error collecting chunks: {e}")
        chunks = [root_path]  # Fallback to single chunk
    
    return chunks


def delete_chunk(chunk_path, progress_tracker=None):
    """
    Delete a single chunk (directory subtree).
    
    Args:
        chunk_path: Path to directory to delete
        progress_tracker: Optional ProgressTracker for reporting
    
    Returns:
        Tuple of (success, path, error_message)
    """
    try:
        shutil.rmtree(chunk_path)
        if progress_tracker:
            progress_tracker.increment(success=True)
        return (True, str(chunk_path), None)
    except Exception as e:
        if progress_tracker:
            progress_tracker.increment(success=False)
        return (False, str(chunk_path), str(e))


def delete_backup_parallel(backup_path, num_threads=5, show_progress=True):
    """
    Delete a backup directory using parallel threads.
    
    Args:
        backup_path: Path to backup directory to delete
        num_threads: Number of threads to use (default: 5)
        show_progress: Whether to show progress bar (default: True)
    
    Returns:
        Tuple of (success, errors_list)
    """
    backup_path = Path(backup_path)
    
    if not backup_path.exists():
        return (False, ["Backup path does not exist"])
    
    print(f"\n  Analyzing directory structure for parallel deletion...")
    
    # Determine optimal depth based on directory structure
    # Try depth 2 first (month level for typical contentstore structure)
    chunks = collect_deletion_chunks(backup_path, max_depth=2)
    
    # If we have very few chunks, try deeper
    if len(chunks) < num_threads * 2:
        chunks = collect_deletion_chunks(backup_path, max_depth=3)
    
    print(f"  Found {len(chunks)} chunks to process with {num_threads} threads")
    
    if len(chunks) <= 1:
        # Not worth parallelizing, use simple deletion
        print(f"  Using single-threaded deletion (insufficient chunks for parallelization)")
        try:
            shutil.rmtree(backup_path)
            return (True, [])
        except Exception as e:
            return (False, [str(e)])
    
    # Set up progress tracking
    progress = ProgressTracker(len(chunks)) if show_progress else None
    errors = []
    
    if show_progress:
        print(f"  Starting parallel deletion...")
    
    # Execute deletions in parallel
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(delete_chunk, chunk, progress) for chunk in chunks]
        
        for future in as_completed(futures):
            if show_progress:
                progress.print_progress()
            
            success, path, error = future.result()
            if not success:
                errors.append(f"{path}: {error}")
    
    if show_progress:
        # Final progress line
        progress.print_progress()
        print()  # New line after progress
    
    # Clean up empty parent directories
    try:
        # Try to remove the root directory (should be empty now)
        if backup_path.exists():
            # Remove any remaining empty directories
            shutil.rmtree(backup_path)
    except Exception as e:
        errors.append(f"Cleanup of parent directory failed: {str(e)}")
    
    return (len(errors) == 0, errors)


def delete_backup_serial(backup_path):
    """
    Delete a backup directory using single-threaded deletion.
    
    Args:
        backup_path: Path to backup directory to delete
    
    Returns:
        Tuple of (success, errors_list)
    """
    try:
        shutil.rmtree(backup_path)
        return (True, [])
    except Exception as e:
        return (False, [str(e)])


def get_s3_config():
    """Load S3 configuration from .env file or environment variables."""
    s3_config = {}
    
    # Try to load from .env file
    env_file = Path('.env')
    if env_file.exists():
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key in ['S3_BUCKET', 'S3_REGION', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY']:
                            s3_config[key] = value
        except Exception as e:
            print(f"Warning: Could not read .env file: {e}")
    
    # Also check environment variables
    for key in ['S3_BUCKET', 'S3_REGION', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY']:
        env_value = os.getenv(key)
        if env_value:
            s3_config[key] = env_value
    
    # Check if S3 is configured
    if s3_config.get('S3_BUCKET') and s3_config.get('AWS_ACCESS_KEY_ID') and s3_config.get('AWS_SECRET_ACCESS_KEY'):
        s3_config['enabled'] = True
        s3_config['region'] = s3_config.get('S3_REGION', 'us-east-1')
    else:
        s3_config['enabled'] = False
    
    return s3_config


def get_rclone_env(access_key_id: str, secret_access_key: str, region: str):
    """Get environment variables for rclone S3 operations."""
    env = os.environ.copy()
    env['RCLONE_CONFIG_S3_TYPE'] = 's3'
    env['RCLONE_CONFIG_S3_PROVIDER'] = 'AWS'
    env['RCLONE_CONFIG_S3_ACCESS_KEY_ID'] = access_key_id
    env['RCLONE_CONFIG_S3_SECRET_ACCESS_KEY'] = secret_access_key
    env['RCLONE_CONFIG_S3_REGION'] = region
    env['RCLONE_CONFIG_S3_ENV_AUTH'] = 'false'
    return env


def check_rclone_installed():
    """Check if rclone is installed."""
    try:
        result = subprocess.run(['rclone', 'version'], capture_output=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def list_s3_postgres_backups(s3_bucket, access_key_id, secret_access_key, region):
    """List PostgreSQL backups in S3."""
    if not check_rclone_installed():
        print("ERROR: rclone is not installed. Cannot list S3 backups.")
        return []
    
    backups = []
    s3_path = f"s3:{s3_bucket}/alfresco-backups/postgres/"
    
    try:
        env = get_rclone_env(access_key_id, secret_access_key, region)
        
        # Use recursive listing to find actual files (handles nested structure)
        cmd = ['rclone', 'lsf', '-R', '--format', 'p', s3_path]
        process = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        
        if process.returncode == 0 and process.stdout:
            seen_timestamps = set()
            for line in process.stdout.strip().split('\n'):
                line = line.strip()
                if not line or not ('postgres-' in line and '.sql.gz' in line):
                    continue
                
                # Handle nested structure: prefix/filename/filename
                # Example: alfresco-backups/postgres/postgres-2026-01-30_17-01-51.sql.gz/postgres-2026-01-30_17-01-51.sql.gz
                parts = line.split('/')
                
                # Find the filename (last non-empty part)
                filename = None
                for part in reversed(parts):
                    part = part.rstrip('/')
                    if part.startswith('postgres-') and part.endswith('.sql.gz'):
                        filename = part
                        break
                
                if not filename:
                    continue
                
                try:
                    timestamp_str = filename.replace('postgres-', '').replace('.sql.gz', '')
                    
                    # Skip if we've already seen this timestamp
                    if timestamp_str in seen_timestamps:
                        continue
                    seen_timestamps.add(timestamp_str)
                    
                    backup_time = datetime.strptime(timestamp_str, '%Y-%m-%d_%H-%M-%S')
                    age_hours = (datetime.now() - backup_time).total_seconds() / 3600
                    age_days = age_hours / 24
                    
                    # Build S3 prefix path (the directory-like path that contains the file)
                    # This is what we need to purge to delete the backup
                    prefix_path = f"alfresco-backups/postgres/{filename}/"
                    
                    backups.append({
                        'type': 'postgres',
                        's3_path': prefix_path,  # Prefix path for deletion
                        'name': filename,
                        'timestamp': backup_time,
                        'age_days': age_days,
                        'size_gb': None  # Size calculation would require additional rclone call
                    })
                except Exception as e:
                    continue
        
        return sorted(backups, key=lambda x: x['timestamp'])
    except Exception as e:
        print(f"ERROR: Failed to list S3 PostgreSQL backups: {e}")
        return []


def list_s3_contentstore_backups(s3_bucket, access_key_id, secret_access_key, region):
    """List contentstore backups in S3 (using folder structure or versioning)."""
    if not check_rclone_installed():
        print("ERROR: rclone is not installed. Cannot list S3 backups.")
        return []
    
    backups = []
    s3_full_path = f"s3:{s3_bucket}/alfresco-backups/contentstore/"
    s3_relative_path = "alfresco-backups/contentstore/"
    
    try:
        env = get_rclone_env(access_key_id, secret_access_key, region)
        
        # Get folder size for contentstore (it's a single synced directory, not timestamped folders)
        # For S3, we can't easily list "backups" since contentstore is synced directly
        # We'll show the current contentstore size and note that S3 versioning handles history
        cmd = ['rclone', 'size', '--json', s3_full_path]
        process = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        
        if process.returncode == 0:
            try:
                import json
                data = json.loads(process.stdout)
                size_bytes = data.get('bytes', 0)
                size_gb = size_bytes / (1024**3)
                
                backups.append({
                    'type': 'contentstore',
                    's3_path': s3_relative_path,
                    'name': 'contentstore (S3 synced)',
                    'timestamp': datetime.now(),  # Current state
                    'age_days': 0,
                    'size_gb': size_gb,
                    'note': 'S3 versioning maintains history - use S3 console to manage versions'
                })
            except Exception:
                pass
        
        return backups
    except Exception as e:
        print(f"ERROR: Failed to list S3 contentstore: {e}")
        return []


def delete_s3_backup(s3_bucket, s3_path, access_key_id, secret_access_key, region, backup_type='postgres'):
    """
    Delete a backup from S3 using rclone.
    
    Args:
        s3_bucket: S3 bucket name
        s3_path: S3 path to delete (relative to bucket, should be a prefix path ending with /)
        access_key_id: AWS access key ID
        secret_access_key: AWS secret access key
        region: AWS region
        backup_type: 'postgres' or 'contentstore'
    
    Returns:
        Tuple of (success, error_message)
    """
    if not check_rclone_installed():
        return (False, "rclone is not installed")
    
    try:
        env = get_rclone_env(access_key_id, secret_access_key, region)
        
        # Ensure path ends with / for prefix/directory deletion
        path_to_delete = s3_path.rstrip('/') + '/'
        s3_full_path = f"s3:{s3_bucket}/{path_to_delete.lstrip('/')}"
        
        # Use rclone purge to delete the entire prefix (directory) and all objects within it
        # This handles the nested structure where files are stored inside prefix directories
        cmd = ['rclone', 'purge', s3_full_path]
        
        process = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
        
        if process.returncode == 0:
            return (True, None)
        else:
            error_msg = process.stderr if process.stderr else process.stdout
            return (False, error_msg[:500])
    except Exception as e:
        return (False, str(e))


def list_contentstore_backups(backup_dir):
    """List all contentstore backups with sizes and ages."""
    contentstore_dir = Path(backup_dir) / 'contentstore'
    
    if not contentstore_dir.exists():
        print(f"ERROR: Contentstore backup directory not found: {contentstore_dir}")
        return []
    
    last_link = contentstore_dir / 'last'
    last_backup = None
    
    if last_link.exists() and last_link.is_symlink():
        last_backup = last_link.resolve()
        print(f"Current successful backup (symlinked by 'last'): {last_backup.name}\n")
    else:
        print("WARNING: No 'last' symlink found - no successful backup yet\n")
    
    backups = []
    
    for item in contentstore_dir.iterdir():
        if item.is_dir() and item.name.startswith('contentstore-'):
            try:
                # Parse timestamp
                timestamp_str = item.name.replace('contentstore-', '')
                backup_time = datetime.strptime(timestamp_str, '%Y-%m-%d_%H-%M-%S')
                age_hours = (datetime.now() - backup_time).total_seconds() / 3600
                age_days = age_hours / 24
                
                # Calculate size
                print(f"Calculating size of {item.name}...")
                size_gb = get_directory_size(item)
                
                is_current = (last_backup and item.resolve() == last_backup)
                
                backups.append({
                    'type': 'local',
                    'path': item,
                    'name': item.name,
                    'timestamp': backup_time,
                    'age_days': age_days,
                    'size_gb': size_gb,
                    'is_current': is_current
                })
            except Exception as e:
                print(f"  WARNING: Could not process {item.name}: {e}")
    
    return sorted(backups, key=lambda x: x['timestamp'])


def main():
    print("=" * 80)
    print("Alfresco Backup Cleanup Tool")
    print("=" * 80)
    
    # Check for S3 configuration
    s3_config = get_s3_config()
    
    if s3_config.get('enabled'):
        print("\nS3 backup mode detected")
        print(f"S3 Bucket: {s3_config.get('S3_BUCKET')}")
        print(f"Region: {s3_config.get('region')}")
        
        if not check_rclone_installed():
            print("\nERROR: rclone is not installed. Cannot clean S3 backups.")
            print("Please install rclone to use S3 cleanup functionality.")
            sys.exit(1)
        
        # List S3 backups
        print("\nAnalyzing S3 backups...")
        postgres_backups = list_s3_postgres_backups(
            s3_config['S3_BUCKET'],
            s3_config['AWS_ACCESS_KEY_ID'],
            s3_config['AWS_SECRET_ACCESS_KEY'],
            s3_config['region']
        )
        
        contentstore_backups = list_s3_contentstore_backups(
            s3_config['S3_BUCKET'],
            s3_config['AWS_ACCESS_KEY_ID'],
            s3_config['AWS_SECRET_ACCESS_KEY'],
            s3_config['region']
        )
        
        all_backups = postgres_backups + contentstore_backups
        
        if not all_backups:
            print("\nNo backups found in S3.")
            return
        
        print("\n" + "=" * 80)
        print("BACKUP SUMMARY (S3)")
        print("=" * 80)
        
        total_size = 0
        for i, backup in enumerate(all_backups, 1):
            size_str = f"{backup['size_gb']:.1f} GB" if backup['size_gb'] else "size unknown"
            print(f"\n{i}. {backup['name']} ({backup['type']})")
            print(f"   Age: {backup['age_days']:.1f} days")
            print(f"   Size: {size_str}")
            if 'note' in backup:
                print(f"   Note: {backup['note']}")
            if backup['size_gb']:
                total_size += backup['size_gb']
        
        if total_size > 0:
            print(f"\nTotal size: {total_size:.1f} GB")
        
        print("\n" + "=" * 80)
        print("CLEANUP OPTIONS")
        print("=" * 80)
        print("\n1. Remove all PostgreSQL backups")
        print("2. Remove specific backups (interactive)")
        print("3. Exit without changes")
        
        choice = input("\nEnter your choice (1-3): ").strip()
        
        if choice == '1':
            # Remove all PostgreSQL backups
            to_remove = [b for b in all_backups if b['type'] == 'postgres']
            
            if not to_remove:
                print("\nNo PostgreSQL backups to remove.")
                return
            
            print(f"\nThis will remove {len(to_remove)} PostgreSQL backup(s):")
            for backup in to_remove:
                print(f"  - {backup['name']}")
            
            confirm = input("\nAre you sure? This cannot be undone! (yes/no): ").strip().lower()
            
            if confirm == 'yes':
                start_time = time.time()
                total_removed = 0
                total_failed = 0
                
                for i, backup in enumerate(to_remove, 1):
                    print(f"\n[{i}/{len(to_remove)}] Removing {backup['name']}...")
                    
                    success, error = delete_s3_backup(
                        s3_config['S3_BUCKET'],
                        backup['s3_path'],
                        s3_config['AWS_ACCESS_KEY_ID'],
                        s3_config['AWS_SECRET_ACCESS_KEY'],
                        s3_config['region'],
                        backup['type']
                    )
                    
                    if success:
                        print(f"  ✓ Removed successfully")
                        total_removed += 1
                    else:
                        print(f"  ✗ Failed: {error}")
                        total_failed += 1
                
                elapsed = time.time() - start_time
                elapsed_min = int(elapsed / 60)
                elapsed_sec = int(elapsed % 60)
                
                print("\n" + "=" * 80)
                print(f"Cleanup complete! Removed {total_removed}/{len(to_remove)} backups in {elapsed_min}m {elapsed_sec}s")
                if total_failed > 0:
                    print(f"Warning: {total_failed} backup(s) failed to delete")
                print("=" * 80)
            else:
                print("\nCleanup cancelled.")
        
        elif choice == '2':
            # Interactive removal
            print("\nSelect backups to remove (enter numbers separated by commas):")
            for i, backup in enumerate(all_backups, 1):
                size_str = f"{backup['size_gb']:.1f} GB" if backup['size_gb'] else "size unknown"
                print(f"{i}. {backup['name']} ({backup['type']}) - {size_str}")
            
            selection = input("\nEnter backup numbers to remove (e.g., 1,3,4): ").strip()
            
            try:
                indices = [int(x.strip()) - 1 for x in selection.split(',')]
                to_remove = []
                
                for idx in indices:
                    if 0 <= idx < len(all_backups):
                        to_remove.append(all_backups[idx])
                
                if not to_remove:
                    print("\nNo valid backups selected.")
                    return
                
                print(f"\nThis will remove {len(to_remove)} backup(s):")
                for backup in to_remove:
                    print(f"  - {backup['name']} ({backup['type']})")
                
                confirm = input("\nAre you sure? This cannot be undone! (yes/no): ").strip().lower()
                
                if confirm == 'yes':
                    start_time = time.time()
                    total_removed = 0
                    total_failed = 0
                    
                    for i, backup in enumerate(to_remove, 1):
                        print(f"\n[{i}/{len(to_remove)}] Removing {backup['name']}...")
                        
                        success, error = delete_s3_backup(
                            s3_config['S3_BUCKET'],
                            backup['s3_path'],
                            s3_config['AWS_ACCESS_KEY_ID'],
                            s3_config['AWS_SECRET_ACCESS_KEY'],
                            s3_config['region'],
                            backup['type']
                        )
                        
                        if success:
                            print(f"  ✓ Removed successfully")
                            total_removed += 1
                        else:
                            print(f"  ✗ Failed: {error}")
                            total_failed += 1
                    
                    elapsed = time.time() - start_time
                    elapsed_min = int(elapsed / 60)
                    elapsed_sec = int(elapsed % 60)
                    
                    print("\n" + "=" * 80)
                    print(f"Cleanup complete! Removed {total_removed}/{len(to_remove)} backups in {elapsed_min}m {elapsed_sec}s")
                    if total_failed > 0:
                        print(f"Warning: {total_failed} backup(s) failed to delete")
                    print("=" * 80)
                else:
                    print("\nCleanup cancelled.")
            
            except (ValueError, IndexError):
                print("\nInvalid selection.")
        
        else:
            print("\nExiting without changes.")
    
    else:
        # Local backup mode
        if len(sys.argv) < 2:
            print("Usage: python3 cleanup_backups.py <backup_directory>")
            print("Example: python3 cleanup_backups.py /mnt/data6tb/backup")
            print("\nNote: For S3 backups, ensure .env file contains S3_BUCKET, AWS_ACCESS_KEY_ID, and AWS_SECRET_ACCESS_KEY")
            sys.exit(1)
        
        backup_dir = Path(sys.argv[1])
        
        if not backup_dir.exists():
            print(f"ERROR: Backup directory not found: {backup_dir}")
            sys.exit(1)
        
        print(f"\nAnalyzing backups in: {backup_dir}\n")
        
        backups = list_contentstore_backups(backup_dir)
        
        if not backups:
            print("No backups found.")
            return
        
        print("\n" + "=" * 80)
        print("BACKUP SUMMARY")
        print("=" * 80)
        
        total_size = 0
        for i, backup in enumerate(backups, 1):
            status = "CURRENT" if backup['is_current'] else "old/failed"
            print(f"\n{i}. {backup['name']}")
            print(f"   Status: {status}")
            print(f"   Age: {backup['age_days']:.1f} days")
            print(f"   Size: {backup['size_gb']:.1f} GB")
            total_size += backup['size_gb']
        
        print(f"\nTotal disk usage: {total_size:.1f} GB")
        
        # Show disk space
        import shutil
        disk_stat = shutil.disk_usage(backup_dir)
        print(f"Available disk space: {disk_stat.free / (1024**3):.1f} GB")
        print(f"Total disk capacity: {disk_stat.total / (1024**3):.1f} GB")
        
        print("\n" + "=" * 80)
        print("CLEANUP OPTIONS")
        print("=" * 80)
        print("\n1. Remove all old/failed backups (keep only CURRENT)")
        print("2. Remove specific backups (interactive)")
        print("3. Exit without changes")
        
        choice = input("\nEnter your choice (1-3): ").strip()
        
        # Ask about deletion method
        use_parallel = True
        num_threads = 5
        
        if choice in ['1', '2']:
            parallel_choice = input("\nUse parallel deletion for faster cleanup? (Y/n): ").strip().lower()
            use_parallel = parallel_choice != 'n'
            
            if use_parallel:
                thread_input = input("Number of threads (default 5, recommended 3-8): ").strip()
                if thread_input:
                    try:
                        num_threads = int(thread_input)
                        if num_threads < 1 or num_threads > 16:
                            print("Warning: Using default of 5 threads (valid range: 1-16)")
                            num_threads = 5
                    except ValueError:
                        print("Warning: Invalid input, using default of 5 threads")
                        num_threads = 5
        
        if choice == '1':
            # Remove all except current
            to_remove = [b for b in backups if not b['is_current']]
            
            if not to_remove:
                print("\nNo old/failed backups to remove.")
                return
            
            print(f"\nThis will remove {len(to_remove)} backup(s):")
            for backup in to_remove:
                print(f"  - {backup['name']} ({backup['size_gb']:.1f} GB)")
            
            total_to_free = sum(b['size_gb'] for b in to_remove)
            print(f"\nTotal space to free: {total_to_free:.1f} GB")
            
            confirm = input("\nAre you sure? This cannot be undone! (yes/no): ").strip().lower()
            
            if confirm == 'yes':
                start_time = time.time()
                total_removed = 0
                total_failed = 0
                
                for i, backup in enumerate(to_remove, 1):
                    print(f"\n[{i}/{len(to_remove)}] Removing {backup['name']} ({backup['size_gb']:.1f} GB)...")
                    
                    if use_parallel:
                        success, errors = delete_backup_parallel(backup['path'], num_threads=num_threads)
                    else:
                        success, errors = delete_backup_serial(backup['path'])
                    
                    if success:
                        print(f"  ✓ Removed successfully")
                        total_removed += 1
                    else:
                        print(f"  ✗ Failed with errors:")
                        for error in errors[:3]:  # Show first 3 errors
                            print(f"    - {error}")
                        if len(errors) > 3:
                            print(f"    ... and {len(errors) - 3} more errors")
                        total_failed += 1
                
                elapsed = time.time() - start_time
                elapsed_min = int(elapsed / 60)
                elapsed_sec = int(elapsed % 60)
                
                print("\n" + "=" * 80)
                print(f"Cleanup complete! Removed {total_removed}/{len(to_remove)} backups in {elapsed_min}m {elapsed_sec}s")
                if total_failed > 0:
                    print(f"Warning: {total_failed} backup(s) failed to delete completely")
                print("=" * 80)
            else:
                print("\nCleanup cancelled.")
        
        elif choice == '2':
            # Interactive removal
            print("\nSelect backups to remove (enter numbers separated by commas):")
            for i, backup in enumerate(backups, 1):
                status = "CURRENT (cannot remove)" if backup['is_current'] else "can remove"
                print(f"{i}. {backup['name']} - {backup['size_gb']:.1f} GB ({status})")
            
            selection = input("\nEnter backup numbers to remove (e.g., 1,3,4): ").strip()
            
            try:
                indices = [int(x.strip()) - 1 for x in selection.split(',')]
                to_remove = []
                
                for idx in indices:
                    if 0 <= idx < len(backups):
                        if backups[idx]['is_current']:
                            print(f"\nWARNING: Skipping {backups[idx]['name']} (current backup)")
                        else:
                            to_remove.append(backups[idx])
                
                if not to_remove:
                    print("\nNo valid backups selected.")
                    return
                
                print(f"\nThis will remove {len(to_remove)} backup(s):")
                for backup in to_remove:
                    print(f"  - {backup['name']} ({backup['size_gb']:.1f} GB)")
                
                total_to_free = sum(b['size_gb'] for b in to_remove)
                print(f"\nTotal space to free: {total_to_free:.1f} GB")
                
                confirm = input("\nAre you sure? This cannot be undone! (yes/no): ").strip().lower()
                
                if confirm == 'yes':
                    start_time = time.time()
                    total_removed = 0
                    total_failed = 0
                    
                    for i, backup in enumerate(to_remove, 1):
                        print(f"\n[{i}/{len(to_remove)}] Removing {backup['name']} ({backup['size_gb']:.1f} GB)...")
                        
                        if use_parallel:
                            success, errors = delete_backup_parallel(backup['path'], num_threads=num_threads)
                        else:
                            success, errors = delete_backup_serial(backup['path'])
                        
                        if success:
                            print(f"  ✓ Removed successfully")
                            total_removed += 1
                        else:
                            print(f"  ✗ Failed with errors:")
                            for error in errors[:3]:  # Show first 3 errors
                                print(f"    - {error}")
                            if len(errors) > 3:
                                print(f"    ... and {len(errors) - 3} more errors")
                            total_failed += 1
                    
                    elapsed = time.time() - start_time
                    elapsed_min = int(elapsed / 60)
                    elapsed_sec = int(elapsed % 60)
                    
                    print("\n" + "=" * 80)
                    print(f"Cleanup complete! Removed {total_removed}/{len(to_remove)} backups in {elapsed_min}m {elapsed_sec}s")
                    if total_failed > 0:
                        print(f"Warning: {total_failed} backup(s) failed to delete completely")
                    print("=" * 80)
                else:
                    print("\nCleanup cancelled.")
            
            except (ValueError, IndexError):
                print("\nInvalid selection.")
        
        else:
            print("\nExiting without changes.")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

