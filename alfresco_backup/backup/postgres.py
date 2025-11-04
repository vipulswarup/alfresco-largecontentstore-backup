"""PostgreSQL backup using pg_dump."""

import os
import subprocess
from datetime import datetime
from pathlib import Path
try:
    from alfresco_backup.utils.subprocess_utils import validate_path
except ImportError:  # pragma: no cover
    from ..utils.subprocess_utils import validate_path


def backup_postgres(config):
    """
    Execute PostgreSQL backup using pg_dump to create a SQL dump file.
    
    Returns dict with keys: success, path, error, duration, start_time, size_uncompressed_mb, size_compressed_mb
    """
    start_time = datetime.now()
    timestamp_str = start_time.strftime('%Y-%m-%d_%H-%M-%S')
    
    postgres_dir = config.backup_dir / 'postgres'
    postgres_dir.mkdir(parents=True, exist_ok=True)
    
    backup_file = postgres_dir / f'postgres-{timestamp_str}.sql.gz'
    temp_uncompressed = postgres_dir / f'postgres-{timestamp_str}.sql.tmp'
    
    result = {
        'success': False,
        'path': str(backup_file),
        'error': None,
        'duration': 0,
        'start_time': start_time.isoformat(),
        'size_uncompressed_mb': 0,
        'size_compressed_mb': 0
    }
    
    # Validate backup path
    try:
        backup_file = validate_path(backup_file, must_exist=False)
    except ValueError as e:
        result['error'] = f"Invalid backup path: {e}"
        return result
    
    # Use embedded PostgreSQL tools to avoid version mismatch
    # Alfresco has its own PostgreSQL 9.4 binaries that match the server version
    embedded_pg_dump = config.alf_base_dir / 'postgresql' / 'bin' / 'pg_dump'
    
    if embedded_pg_dump.exists():
        pg_dump_cmd = str(embedded_pg_dump)
        print(f"Using embedded pg_dump: {pg_dump_cmd}")
    else:
        pg_dump_cmd = 'pg_dump'
        print(f"Embedded pg_dump not found, using system version: {pg_dump_cmd}")
    
    # Set PGPASSWORD for pg_dump
    env = {
        'PGPASSWORD': config.pgpassword,
        'PATH': os.environ.get('PATH', '')
    }
    
    # Use pg_dump with gzip compression
    # pg_dump outputs to stdout, which we pipe to gzip
    pg_dump_cmd_list = [
        pg_dump_cmd,
        '-h', config.pghost,
        '-p', config.pgport,
        '-U', config.pguser,
        '-d', config.pgdatabase,
        '--clean',  # Include DROP statements
        '--if-exists',  # Use IF EXISTS for DROP statements
        '--no-owner',  # Skip ownership commands
        '--no-acl',  # Skip access privileges
    ]
    
    # Run pg_dump first to temporary file to get uncompressed size
    try:
        # Step 1: Create uncompressed dump to measure size
        with open(temp_uncompressed, 'wb') as out_file:
            pg_dump_process = subprocess.Popen(
                pg_dump_cmd_list,
                env=env,
                stdout=out_file,
                stderr=subprocess.PIPE
            )
            
            pg_dump_stderr = pg_dump_process.communicate()[1]
            
            if pg_dump_process.returncode != 0:
                error_msg = pg_dump_stderr.decode('utf-8', errors='replace') if pg_dump_stderr else 'Unknown error'
                result['error'] = f"pg_dump failed with exit code {pg_dump_process.returncode}: {error_msg}"
                if temp_uncompressed.exists():
                    temp_uncompressed.unlink()
                return result
        
        # Get uncompressed size
        if temp_uncompressed.exists():
            uncompressed_size = temp_uncompressed.stat().st_size
            result['size_uncompressed_mb'] = uncompressed_size / (1024 * 1024)
        else:
            result['error'] = "pg_dump completed but no output file was created"
            return result
        
        # Step 2: Compress the dump file
        with open(temp_uncompressed, 'rb') as in_file:
            with open(backup_file, 'wb') as out_file:
                gzip_process = subprocess.Popen(
                    ['gzip', '-c'],
                    stdin=in_file,
                    stdout=out_file,
                    stderr=subprocess.PIPE
                )
                
                gzip_stderr = gzip_process.communicate()[1]
                
                if gzip_process.returncode != 0:
                    error_msg = gzip_stderr.decode('utf-8', errors='replace') if gzip_stderr else 'Unknown error'
                    result['error'] = f"gzip failed with exit code {gzip_process.returncode}: {error_msg}"
                    if backup_file.exists():
                        backup_file.unlink()
                    if temp_uncompressed.exists():
                        temp_uncompressed.unlink()
                    return result
        
        # Get compressed size
        if backup_file.exists():
            compressed_size = backup_file.stat().st_size
            result['size_compressed_mb'] = compressed_size / (1024 * 1024)
        else:
            result['error'] = "gzip completed but no compressed file was created"
            if temp_uncompressed.exists():
                temp_uncompressed.unlink()
            return result
        
        # Clean up temporary uncompressed file
        if temp_uncompressed.exists():
            temp_uncompressed.unlink()
        
        # Verify backup file was created and has content
        if backup_file.exists() and backup_file.stat().st_size > 1024:  # At least 1KB
            result['success'] = True
            result['duration'] = (datetime.now() - start_time).total_seconds()
        else:
            result['error'] = "Backup file created but is suspiciously small or empty"
            if backup_file.exists():
                backup_file.unlink()
    
    except subprocess.TimeoutExpired:
        result['error'] = f"Backup timed out after 2 hours"
        if backup_file.exists():
            backup_file.unlink()
    except FileNotFoundError:
        result['error'] = f"Command not found: {pg_dump_cmd}"
    except Exception as e:
        result['error'] = f"Unexpected error during backup: {str(e)}"
        if backup_file.exists():
            backup_file.unlink()
    
    return result

