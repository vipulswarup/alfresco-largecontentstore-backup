#!/usr/bin/env python3
"""
Manual cleanup script for Alfresco backups.
Use this to free up disk space by removing old or failed backup attempts.
Features multithreaded deletion for faster cleanup of large backups.
"""

import os
import sys
import shutil
import threading
import time
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
    if len(sys.argv) < 2:
        print("Usage: python3 cleanup_backups.py <backup_directory>")
        print("Example: python3 cleanup_backups.py /mnt/data6tb/backup")
        sys.exit(1)
    
    backup_dir = Path(sys.argv[1])
    
    if not backup_dir.exists():
        print(f"ERROR: Backup directory not found: {backup_dir}")
        sys.exit(1)
    
    print("=" * 80)
    print("Alfresco Backup Cleanup Tool")
    print("=" * 80)
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

