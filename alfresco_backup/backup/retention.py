"""Retention policy enforcement - cleanup old backups."""

import time
import shutil
from pathlib import Path
from datetime import datetime


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
                    item.name.startswith('contentstore-')):
                    # Parse timestamp from directory name (contentstore-YYYY-MM-DD_HH-MM-SS)
                    try:
                        # Extract timestamp from directory name
                        timestamp_str = item.name.replace('contentstore-', '')
                        # Parse the timestamp
                        backup_time = datetime.strptime(timestamp_str, '%Y-%m-%d_%H-%M-%S')
                        backup_timestamp = backup_time.timestamp()
                        
                        # Check if backup is older than retention period
                        if backup_timestamp < time.time() - (config.retention_days * 86400):
                            shutil.rmtree(item)
                            deleted.append(f"Contentstore: {item}")
                    except ValueError:
                        # If we can't parse the timestamp, fall back to file modification time
                        if item.stat().st_mtime < time.time() - (config.retention_days * 86400):
                            try:
                                shutil.rmtree(item)
                                deleted.append(f"Contentstore: {item}")
                            except Exception as e:
                                errors.append(f"Failed to delete {item}: {str(e)}")
                    except Exception as e:
                        errors.append(f"Failed to delete {item}: {str(e)}")
    
    except Exception as e:
        errors.append(f"Error cleaning contentstore backups: {str(e)}")
    
    # Clean up old PostgreSQL backups
    try:
        postgres_dir = config.backup_dir / 'postgres'
        if postgres_dir.exists():
            for item in postgres_dir.iterdir():
                if (item.is_file() and 
                    item.name.startswith('postgres-') and 
                    item.name.endswith('.sql.gz')):
                    # Parse timestamp from filename (postgres-YYYY-MM-DD_HH-MM-SS.sql.gz)
                    try:
                        # Extract timestamp from filename
                        timestamp_str = item.name.replace('postgres-', '').replace('.sql.gz', '')
                        # Parse the timestamp
                        backup_time = datetime.strptime(timestamp_str, '%Y-%m-%d_%H-%M-%S')
                        backup_timestamp = backup_time.timestamp()
                        
                        # Check if backup is older than retention period
                        if backup_timestamp < time.time() - (config.retention_days * 86400):
                            item.unlink()
                            deleted.append(f"PostgreSQL: {item}")
                    except ValueError:
                        # If we can't parse the timestamp, fall back to file modification time
                        if item.stat().st_mtime < time.time() - (config.retention_days * 86400):
                            try:
                                item.unlink()
                                deleted.append(f"PostgreSQL: {item}")
                            except Exception as e:
                                errors.append(f"Failed to delete {item}: {str(e)}")
                    except Exception as e:
                        errors.append(f"Failed to delete {item}: {str(e)}")
    
    except Exception as e:
        errors.append(f"Error cleaning PostgreSQL backups: {str(e)}")
    
    # Build result
    result['deleted_items'] = deleted
    
    if errors:
        result['error'] = '\n'.join(errors)
        result['success'] = False
    else:
        result['success'] = True
    
    return result

