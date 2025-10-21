#!/usr/bin/env python3
"""Debug script to test retention logic."""

import time
import os
from pathlib import Path
from datetime import datetime

def debug_retention_logic():
    """Debug the retention logic to see why it's deleting recent backups."""
    
    print("=== RETENTION DEBUG ===")
    print(f"Current time: {datetime.now()}")
    print(f"Current timestamp: {time.time()}")
    print(f"Current time (formatted): {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Check backup directories
    backup_base = Path("/mnt/backups/alfresco")
    
    if not backup_base.exists():
        print(f"Backup directory does not exist: {backup_base}")
        return
    
    # Check contentstore backups
    contentstore_dir = backup_base / 'contentstore'
    if contentstore_dir.exists():
        print("=== CONTENTSTORE BACKUPS ===")
        for item in contentstore_dir.iterdir():
            if item.is_dir() and item.name.startswith(('daily-', 'contentstore-')):
                mtime = item.stat().st_mtime
                mtime_formatted = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                
                # Calculate age
                age_seconds = time.time() - mtime
                age_days = age_seconds / 86400
                
                # Test retention logic
                retention_days = 7
                should_delete = mtime < time.time() - (retention_days * 86400)
                
                print(f"Directory: {item.name}")
                print(f"  Modified: {mtime_formatted}")
                print(f"  Timestamp: {mtime}")
                print(f"  Age: {age_days:.2f} days")
                print(f"  Should delete (7 days): {should_delete}")
                print()
    
    # Check postgres backups
    postgres_dir = backup_base / 'postgres'
    if postgres_dir.exists():
        print("=== POSTGRES BACKUPS ===")
        for item in postgres_dir.iterdir():
            if item.is_dir() and item.name.startswith('base-'):
                mtime = item.stat().st_mtime
                mtime_formatted = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                
                # Calculate age
                age_seconds = time.time() - mtime
                age_days = age_seconds / 86400
                
                # Test retention logic
                retention_days = 7
                should_delete = mtime < time.time() - (retention_days * 86400)
                
                print(f"Directory: {item.name}")
                print(f"  Modified: {mtime_formatted}")
                print(f"  Timestamp: {mtime}")
                print(f"  Age: {age_days:.2f} days")
                print(f"  Should delete (7 days): {should_delete}")
                print()

if __name__ == "__main__":
    debug_retention_logic()
