"""Retention policy enforcement - cleanup old backups."""

import subprocess
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
        cmd = [
            'find', str(contentstore_dir),
            '-maxdepth', '1',
            '-type', 'd',
            '-name', 'daily-*',
            '-mtime', f'+{config.retention_days}'
        ]
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if process.returncode == 0 and process.stdout.strip():
            old_dirs = process.stdout.strip().split('\n')
            for old_dir in old_dirs:
                try:
                    subprocess.run(['rm', '-rf', old_dir], check=True, timeout=300)
                    deleted.append(f"Contentstore: {old_dir}")
                except Exception as e:
                    errors.append(f"Failed to delete {old_dir}: {str(e)}")
    
    except Exception as e:
        errors.append(f"Error cleaning contentstore backups: {str(e)}")
    
    # Clean up old PostgreSQL backups
    try:
        postgres_dir = config.backup_dir / 'postgres'
        cmd = [
            'find', str(postgres_dir),
            '-maxdepth', '1',
            '-type', 'd',
            '-name', 'base-*',
            '-mtime', f'+{config.retention_days}'
        ]
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if process.returncode == 0 and process.stdout.strip():
            old_dirs = process.stdout.strip().split('\n')
            for old_dir in old_dirs:
                try:
                    subprocess.run(['rm', '-rf', old_dir], check=True, timeout=300)
                    deleted.append(f"PostgreSQL: {old_dir}")
                except Exception as e:
                    errors.append(f"Failed to delete {old_dir}: {str(e)}")
    
    except Exception as e:
        errors.append(f"Error cleaning PostgreSQL backups: {str(e)}")
    
    # Clean up old WAL files
    try:
        wal_dir = config.backup_dir / 'pg_wal'
        cmd = [
            'find', str(wal_dir),
            '-type', 'f',
            '-mtime', f'+{config.retention_days}',
            '-delete'
        ]
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if process.returncode == 0:
            deleted.append(f"WAL files older than {config.retention_days} days")
        else:
            errors.append(f"Failed to delete old WAL files: {process.stderr}")
    
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

