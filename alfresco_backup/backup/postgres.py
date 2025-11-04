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
    
    Returns dict with keys: success, path, error, duration, start_time
    """
    start_time = datetime.now()
    timestamp_str = start_time.strftime('%Y-%m-%d_%H-%M-%S')
    
    postgres_dir = config.backup_dir / 'postgres'
    postgres_dir.mkdir(parents=True, exist_ok=True)
    
    backup_file = postgres_dir / f'postgres-{timestamp_str}.sql.gz'
    
    result = {
        'success': False,
        'path': str(backup_file),
        'error': None,
        'duration': 0,
        'start_time': start_time.isoformat()
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
    
    # Run pg_dump and pipe to gzip
    try:
        # Open output file for writing
        with open(backup_file, 'wb') as out_file:
            # Start pg_dump process
            pg_dump_process = subprocess.Popen(
                pg_dump_cmd_list,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Start gzip process
            gzip_process = subprocess.Popen(
                ['gzip'],
                stdin=pg_dump_process.stdout,
                stdout=out_file,
                stderr=subprocess.PIPE
            )
            
            # Close pg_dump's stdout to allow it to receive SIGPIPE if gzip fails
            pg_dump_process.stdout.close()
            
            # Wait for both processes
            pg_dump_stdout, pg_dump_stderr = pg_dump_process.communicate()
            gzip_stdout, gzip_stderr = gzip_process.communicate()
            
            # Check results
            if pg_dump_process.returncode != 0:
                error_msg = pg_dump_stderr.decode('utf-8', errors='replace') if pg_dump_stderr else 'Unknown error'
                result['error'] = f"pg_dump failed with exit code {pg_dump_process.returncode}: {error_msg}"
                # Clean up partial file
                if backup_file.exists():
                    backup_file.unlink()
                return result
            
            if gzip_process.returncode != 0:
                error_msg = gzip_stderr.decode('utf-8', errors='replace') if gzip_stderr else 'Unknown error'
                result['error'] = f"gzip failed with exit code {gzip_process.returncode}: {error_msg}"
                # Clean up partial file
                if backup_file.exists():
                    backup_file.unlink()
                return result
        
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

