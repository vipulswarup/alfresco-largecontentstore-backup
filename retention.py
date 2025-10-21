"""Retention policy enforcement - cleanup old backups."""

import time
import shutil
from pathlib import Path


def apply_retention(config):
    """
    Apply retention policy to delete old backups.
    
    Returns dict with keys: success, deleted_items, error
    """
    result = {
        'success': False,
        'deleted_items': [],
        'error': None
    }
    
    errors = []
    deleted = []
    
    # Clean up old contentstore backups
    try:
        contentstore_dir = config.backup_dir / 'contentstore'
        if contentstore_dir.exists():
            for item in contentstore_dir.iterdir():
                if (item.is_dir() and 
                    item.name.startswith('contentstore-') and 
                    item.stat().st_mtime < time.time() - (config.retention_days * 86400)):
                    try:
                        shutil.rmtree(item)
                        deleted.append(f"Contentstore: {item}")
                    except Exception as e:
                        errors.append(f"Failed to delete {item}: {str(e)}")
    
    except Exception as e:
        errors.append(f"Error cleaning contentstore backups: {str(e)}")
    
    # Clean up old PostgreSQL backups
    try:
        postgres_dir = config.backup_dir / 'postgres'
        if postgres_dir.exists():
            for item in postgres_dir.iterdir():
                if (item.is_dir() and 
                    item.name.startswith('base-') and 
                    item.stat().st_mtime < time.time() - (config.retention_days * 86400)):
                    try:
                        shutil.rmtree(item)
                        deleted.append(f"PostgreSQL: {item}")
                    except Exception as e:
                        errors.append(f"Failed to delete {item}: {str(e)}")
    
    except Exception as e:
        errors.append(f"Error cleaning PostgreSQL backups: {str(e)}")
    
    # Clean up old WAL files
    try:
        wal_dir = config.backup_dir / 'pg_wal'
        if wal_dir.exists():
            wal_files_deleted = 0
            for item in wal_dir.iterdir():
                if (item.is_file() and 
                    item.stat().st_mtime < time.time() - (config.retention_days * 86400)):
                    try:
                        item.unlink()
                        wal_files_deleted += 1
                    except Exception as e:
                        errors.append(f"Failed to delete WAL file {item}: {str(e)}")
            if wal_files_deleted > 0:
                deleted.append(f"WAL files: {wal_files_deleted} files older than {config.retention_days} days")
    
    except Exception as e:
        errors.append(f"Error cleaning WAL files: {str(e)}")
    
    # Build result
    result['deleted_items'] = deleted
    
    if errors:
        result['error'] = '\n'.join(errors)
        result['success'] = False
    else:
        result['success'] = True
    
    return result

