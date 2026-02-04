#!/usr/bin/env python3
"""
Alfresco Automated Restore System

Automated restore procedures for Alfresco backups with PostgreSQL and contentstore recovery.
"""

import os
import sys
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from argparse import ArgumentParser
from typing import Dict, List, Optional, Tuple
import tempfile
try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    class _DummyTqdm:
        def __init__(self, iterable=None, total=None, unit=None, desc=None):
            self._iterable = iterable if iterable is not None else range(total or 0)

        def __iter__(self):
            return iter(self._iterable)

        def update(self, *_args, **_kwargs):
            return None

        def close(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def tqdm(iterable=None, total=None, **_kwargs):  # type: ignore
        return _DummyTqdm(iterable=iterable, total=total)


class RestoreConfig:
    """Configuration for restore operations."""
    
    def __init__(self):
        # Default to current user, will be overridden by .env or prompt
        self.alfresco_user = os.environ.get('USER', os.environ.get('USERNAME', 'alfresco'))
        self.backup_dir = None
        self.alf_base_dir = None
        self.postgres_data_dir = None
        self.contentstore_dir = None
        self.alfresco_script = None
        self.restore_log_dir = None
        self.s3_enabled = False
        self.s3_bucket = None
        self.s3_region = None
        self.s3_access_key_id = None
        self.s3_secret_access_key = None
        
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate configuration and return (success, errors)."""
        errors = []
        
        if not self.s3_enabled:
            if not self.backup_dir or not Path(self.backup_dir).exists():
                errors.append(f"Backup directory does not exist: {self.backup_dir}")
        else:
            if not self.s3_bucket or not self.s3_access_key_id or not self.s3_secret_access_key:
                errors.append("S3 configuration incomplete: S3_BUCKET, AWS_ACCESS_KEY_ID, and AWS_SECRET_ACCESS_KEY required")
        
        if not self.alf_base_dir or not Path(self.alf_base_dir).exists():
            errors.append(f"Alfresco base directory does not exist: {self.alf_base_dir}")
        
        if self.alf_base_dir:
            # Ensure alf_base_dir is a Path object
            alf_base_path = Path(self.alf_base_dir) if isinstance(self.alf_base_dir, str) else self.alf_base_dir
            pg_root = alf_base_path / 'alf_data' / 'postgresql'
            pg_data_candidate = pg_root / 'data'
            if (pg_root / 'PG_VERSION').exists():
                self.postgres_data_dir = pg_root
            elif (pg_data_candidate / 'PG_VERSION').exists():
                self.postgres_data_dir = pg_data_candidate
            else:
                self.postgres_data_dir = pg_root

            self.contentstore_dir = alf_base_path / 'alf_data' / 'contentstore'
            self.alfresco_script = alf_base_path / 'alfresco.sh'
            
            if not self.alfresco_script.exists():
                errors.append(f"Alfresco control script not found: {self.alfresco_script}")
        
        return len(errors) == 0, errors


class RestoreLogger:
    """Dual logging to console and file."""
    
    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger('alfresco_restore')
        self.logger.setLevel(logging.INFO)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', 
                                     datefmt='%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def info(self, message: str):
        self.logger.info(message)
    
    def warning(self, message: str):
        self.logger.warning(message)
    
    def error(self, message: str, exc_info=None):
        if exc_info:
            self.logger.error(message, exc_info=exc_info)
        else:
            self.logger.error(message)
    
    def section(self, title: str):
        separator = "=" * 80
        self.info("")
        self.info(separator)
        self.info(f"  {title}")
        self.info(separator)
class AlfrescoRestore:
    """Main restore orchestrator."""
    
    def __init__(self, config: RestoreConfig, logger: RestoreLogger):
        self.config = config
        self.logger = logger
        
    def start_alfresco_full(self) -> bool:
        """Start all Alfresco services (including PostgreSQL)."""
        self.logger.info("Starting all Alfresco services...")
        
        # Check if PostgreSQL data directory exists, initialize if not
        if self.config.postgres_data_dir and not self.config.postgres_data_dir.exists():
            self.logger.warning(f"PostgreSQL data directory does not exist: {self.config.postgres_data_dir}")
            self.logger.info("Initializing PostgreSQL data directory...")
            
            # Find initdb binary
            alf_base_path = Path(self.config.alf_base_dir) if isinstance(self.config.alf_base_dir, str) else self.config.alf_base_dir
            embedded_initdb = alf_base_path / 'postgresql' / 'bin' / 'initdb'
            if embedded_initdb.exists():
                initdb_cmd = str(embedded_initdb)
            else:
                initdb_cmd = 'initdb'
            
            try:
                # Create parent directory if needed
                self.config.postgres_data_dir.parent.mkdir(parents=True, exist_ok=True)
                
                # Initialize PostgreSQL
                result = subprocess.run(
                    ['sudo', '-u', self.config.alfresco_user, initdb_cmd,
                     '-D', str(self.config.postgres_data_dir)],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                
                if result.returncode == 0:
                    self.logger.info("PostgreSQL data directory initialized successfully")
                else:
                    self.logger.error(f"Failed to initialize PostgreSQL: {result.stderr}")
                    return False
            except Exception as e:
                self.logger.error(f"Error initializing PostgreSQL: {e}")
                return False
        
        try:
            # Start services - don't fail on non-zero return code as services may still be starting
            result = subprocess.run(
                ['sudo', '-u', self.config.alfresco_user, 
                 str(self.config.alfresco_script), 'start'],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            # Log output but don't fail yet - services may still be starting
            if result.stdout:
                self.logger.info(f"Start command output: {result.stdout}")
            if result.stderr:
                self.logger.info(f"Start command error: {result.stderr}")
            
            # Wait and poll catalina.out for successful startup
            self.logger.info("Waiting for Alfresco to start (checking catalina.out)...")
            return self._wait_for_alfresco_startup(max_wait_minutes=4)
                
        except subprocess.TimeoutExpired:
            self.logger.error("Alfresco start command timed out")
            # Still try to wait for startup
            self.logger.info("Waiting for Alfresco to start (checking catalina.out)...")
            return self._wait_for_alfresco_startup(max_wait_minutes=4)
        except Exception as e:
            self.logger.error(f"Error starting Alfresco: {e}")
            return False
    
    def _wait_for_alfresco_startup(self, max_wait_minutes: int = 4) -> bool:
        """
        Wait for Alfresco to start by polling catalina.out for 'Server startup' message.
        
        Args:
            max_wait_minutes: Maximum time to wait in minutes (default: 4)
        
        Returns:
            True if startup detected, False if timeout
        """
        import time
        
        alf_base_path = Path(self.config.alf_base_dir) if isinstance(self.config.alf_base_dir, str) else self.config.alf_base_dir
        catalina_log = alf_base_path / 'tomcat' / 'logs' / 'catalina.out'
        
        if not catalina_log.exists():
            self.logger.warning(f"catalina.out not found at {catalina_log}, waiting {max_wait_minutes} minutes...")
            time.sleep(max_wait_minutes * 60)
            return True  # Assume success if we can't check
        
        max_wait_seconds = max_wait_minutes * 60
        check_interval = 5  # Check every 5 seconds
        elapsed = 0
        
        self.logger.info(f"Polling {catalina_log} for 'Server startup' message (max {max_wait_minutes} minutes)...")
        
        while elapsed < max_wait_seconds:
            try:
                # Read the last few KB of the log file
                with open(catalina_log, 'rb') as f:
                    # Seek to end and read last 50KB
                    f.seek(0, 2)  # Seek to end
                    file_size = f.tell()
                    read_size = min(50000, file_size)
                    f.seek(max(0, file_size - read_size))
                    log_tail = f.read().decode('utf-8', errors='ignore')
                
                # Check for successful startup message
                if 'Server startup in' in log_tail and 'ms' in log_tail:
                    # Extract the startup line
                    for line in log_tail.split('\n'):
                        if 'Server startup in' in line and 'ms' in line:
                            self.logger.info(f"Alfresco started successfully: {line.strip()}")
                            return True
                
                # Check for fatal errors that indicate startup failure
                if 'SEVERE' in log_tail or 'FATAL' in log_tail:
                    # Check if it's a recent error (in last 30 seconds of log)
                    recent_errors = [line for line in log_tail.split('\n')[-100:] 
                                   if 'SEVERE' in line or 'FATAL' in line]
                    if recent_errors:
                        self.logger.warning(f"Found errors in catalina.out: {recent_errors[-1]}")
                
            except Exception as e:
                self.logger.debug(f"Error reading catalina.out: {e}")
            
            time.sleep(check_interval)
            elapsed += check_interval
            
            if elapsed % 30 == 0:  # Log progress every 30 seconds
                self.logger.info(f"Still waiting... ({elapsed // 60}m {elapsed % 60}s elapsed)")
        
        # Timeout - check if services are at least running
        self.logger.warning(f"Timeout waiting for 'Server startup' message after {max_wait_minutes} minutes")
        self.logger.info("Checking if Tomcat process is running...")
        
        try:
            result = subprocess.run(
                ['pgrep', '-f', 'java.*tomcat|java.*alfresco.*tomcat'],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                self.logger.info("Tomcat process is running - assuming startup successful")
                return True
        except Exception:
            pass
        
        self.logger.error("Alfresco startup verification failed")
        return False
    
    def stop_tomcat_only(self) -> bool:
        """Stop only Tomcat, leaving PostgreSQL running."""
        self.logger.info("Stopping Tomcat only (PostgreSQL will remain running)...")
        
        try:
            # Try to stop tomcat using alfresco.sh stop-tomcat or similar
            # If that doesn't work, try to kill tomcat processes directly
            result = subprocess.run(
                ['sudo', '-u', self.config.alfresco_user, 
                 str(self.config.alfresco_script), 'stop-tomcat'],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                self.logger.info("Tomcat stopped successfully")
                return True
            else:
                # Fallback: try to stop tomcat by finding and killing the process
                self.logger.info("Attempting alternative method to stop Tomcat...")
                return self._stop_tomcat_process()
                
        except subprocess.TimeoutExpired:
            self.logger.error("Tomcat stop timed out")
            return False
        except Exception as e:
            self.logger.error(f"Error stopping Tomcat: {e}")
            return False
    
    def _stop_tomcat_process(self) -> bool:
        """Stop Tomcat by finding and killing the Java process."""
        try:
            # Find tomcat process (java process with tomcat/alfresco in classpath)
            result = subprocess.run(
                ['pgrep', '-f', 'java.*tomcat|java.*alfresco.*tomcat'],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid:
                        self.logger.info(f"Stopping Tomcat process {pid}")
                        subprocess.run(['sudo', '-u', self.config.alfresco_user, 'kill', pid], check=False)
                
                # Wait a bit for processes to stop
                import time
                time.sleep(5)
                
                # Verify tomcat is stopped
                result = subprocess.run(['pgrep', '-f', 'java.*tomcat|java.*alfresco.*tomcat'], capture_output=True)
                if result.returncode != 0:
                    self.logger.info("Tomcat stopped successfully")
                    return True
                else:
                    self.logger.warning("Some Tomcat processes may still be running")
                    return True
            else:
                self.logger.info("No Tomcat processes found (may already be stopped)")
                return True
                
        except Exception as e:
            self.logger.error(f"Error stopping Tomcat process: {e}")
            return False
    
    def verify_postgresql_running(self) -> bool:
        """Verify that PostgreSQL is running and accepting connections."""
        self.logger.info("Verifying PostgreSQL is running...")
        
        try:
            # Try to connect to PostgreSQL using psql
            import os
            
            # Try to load .env file
            try:
                from dotenv import load_dotenv
                load_dotenv()
            except ImportError:
                # dotenv not available, try to read .env manually
                try:
                    env_file = Path('.env')
                    if env_file.exists():
                        with open(env_file, 'r') as f:
                            for line in f:
                                line = line.strip()
                                if line and not line.startswith('#') and '=' in line:
                                    key, value = line.split('=', 1)
                                    key = key.strip()
                                    value = value.strip().strip('"').strip("'")
                                    os.environ[key] = value
                except Exception:
                    pass  # Continue with environment variables as-is
            
            pg_host = os.getenv('PGHOST', 'localhost')
            pg_port = os.getenv('PGPORT', '5432')
            pg_user = os.getenv('PGUSER', 'alfresco')
            pg_password = os.getenv('PGPASSWORD')
            pg_database = os.getenv('PGDATABASE', 'postgres')
            
            # Use embedded psql if available
            alf_base_path = Path(self.config.alf_base_dir) if isinstance(self.config.alf_base_dir, str) else self.config.alf_base_dir
            embedded_psql = alf_base_path / 'postgresql' / 'bin' / 'psql'
            if embedded_psql.exists():
                psql_cmd = str(embedded_psql)
            else:
                psql_cmd = 'psql'
            
            env = os.environ.copy()
            if pg_password:
                env['PGPASSWORD'] = pg_password
            
            # Try connecting as the configured user
            result = subprocess.run(
                [psql_cmd, '-h', pg_host, '-p', pg_port, '-U', pg_user, '-d', pg_database, '-c', 'SELECT 1;'],
                env=env,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                self.logger.info("PostgreSQL is running and accepting connections")
                return True
            else:
                # Check if it's a user/role error
                if 'does not exist' in result.stderr or 'role' in result.stderr.lower():
                    self.logger.error(f"PostgreSQL user '{pg_user}' does not exist")
                    self.logger.error("The 'alfresco' user is created during Alfresco installation and cannot be recreated.")
                    self.logger.error("If the user was deleted, you must reinstall Alfresco.")
                    self.logger.error(f"Connection error: {result.stderr}")
                else:
                    self.logger.error(f"PostgreSQL connection failed: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error verifying PostgreSQL: {e}")
            return False
    
    def stop_alfresco(self) -> bool:
        """Stop Alfresco and PostgreSQL services (legacy method, kept for compatibility)."""
        self.logger.info("Stopping Alfresco services...")
        
        try:
            result = subprocess.run(
                ['sudo', '-u', self.config.alfresco_user, 
                 str(self.config.alfresco_script), 'stop'],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                self.logger.info("Alfresco services stopped successfully")
                return True
            else:
                self.logger.warning(f"Stop command output: {result.stdout}")
                self.logger.warning(f"Stop command error: {result.stderr}")
                return True
                
        except subprocess.TimeoutExpired:
            self.logger.error("Alfresco stop timed out")
            return False
        except Exception as e:
            self.logger.error(f"Error stopping Alfresco: {e}")
            return False
    
    def verify_stopped(self) -> bool:
        """Verify that Alfresco and PostgreSQL are stopped."""
        try:
            result = subprocess.run(['pgrep', '-f', 'java.*alfresco'],
                                  capture_output=True)
            if result.returncode == 0:
                self.logger.error("Alfresco Java processes are still running!")
                return False
            
            self.logger.info("Verified services are stopped")
            return True
        except Exception as e:
            self.logger.warning(f"Could not verify services stopped: {e}")
            return True
    
    def backup_current_data(self) -> Tuple[bool, str]:
        """Backup current data before restore."""
        self.logger.info("Creating backup of current data...")
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        
        try:
            if self.config.postgres_data_dir and self.config.postgres_data_dir.exists():
                backup_name = f"{self.config.postgres_data_dir.name}.backup.{timestamp}"
                backup_pg = self.config.postgres_data_dir.parent / backup_name
                subprocess.run(['sudo', 'mv', str(self.config.postgres_data_dir), str(backup_pg)], check=True)
                self.logger.info(f"Backed up PostgreSQL data to: {backup_pg}")
            
            if self.config.contentstore_dir and self.config.contentstore_dir.exists():
                backup_cs = self.config.contentstore_dir.parent / f'contentstore.backup.{timestamp}'
                subprocess.run(['sudo', 'mv', str(self.config.contentstore_dir), str(backup_cs)], check=True)
                self.logger.info(f"Backed up contentstore to: {backup_cs}")
            
            return True, timestamp
            
        except Exception as e:
            self.logger.error(f"Failed to backup current data: {e}")
            return False, ""
    
    def list_postgres_backups(self) -> List[str]:
        """List available PostgreSQL backups."""
        if self.config.s3_enabled:
            try:
                from alfresco_backup.utils.s3_utils import list_s3_postgres_backups
                return list_s3_postgres_backups(
                    self.config.s3_bucket,
                    self.config.s3_access_key_id,
                    self.config.s3_secret_access_key,
                    self.config.s3_region
                )
            except Exception as e:
                self.logger.error(f"Error listing S3 PostgreSQL backups: {e}")
                return []
        
        backup_dir = Path(self.config.backup_dir) / 'postgres'
        if not backup_dir.exists():
            return []
        
        backups = []
        for item in backup_dir.iterdir():
            if item.is_file() and item.name.startswith('postgres-') and item.name.endswith('.sql.gz'):
                timestamp = item.name.replace('postgres-', '').replace('.sql.gz', '')
                backups.append(timestamp)
        
        return sorted(backups, reverse=True)
    
    def list_contentstore_backups(self) -> List[str]:
        """List available contentstore backups."""
        if self.config.s3_enabled:
            try:
                from alfresco_backup.utils.s3_utils import list_s3_contentstore_versions
                versions = list_s3_contentstore_versions(
                    self.config.s3_bucket,
                    self.config.s3_access_key_id,
                    self.config.s3_secret_access_key,
                    self.config.s3_region
                )
                return [v['timestamp'].strftime('%Y-%m-%d_%H-%M-%S') for v in versions]
            except Exception as e:
                self.logger.error(f"Error listing S3 contentstore versions: {e}")
                return []
        
        backup_dir = Path(self.config.backup_dir) / 'contentstore'
        if not backup_dir.exists():
            return []
        
        backups = []
        for item in backup_dir.iterdir():
            if item.is_dir() and item.name.startswith('contentstore-'):
                timestamp = item.name.replace('contentstore-', '')
                backups.append(timestamp)
        
        return sorted(backups, reverse=True)
    
    def validate_postgres_backup(self, timestamp: str) -> bool:
        """Validate PostgreSQL backup exists and has content."""
        if self.config.s3_enabled:
            try:
                from alfresco_backup.utils.s3_utils import check_rclone_installed
                if not check_rclone_installed():
                    self.logger.error("rclone is not installed. Please install rclone to use S3 restore.")
                    return False
                
                backups = self.list_postgres_backups()
                if timestamp in backups:
                    self.logger.info(f"PostgreSQL backup found in S3: {timestamp}")
                    return True
                else:
                    self.logger.error(f"PostgreSQL backup not found in S3: {timestamp}")
                    return False
            except Exception as e:
                self.logger.error(f"Error validating S3 PostgreSQL backup: {e}")
                return False
        
        backup_file = Path(self.config.backup_dir) / 'postgres' / f'postgres-{timestamp}.sql.gz'
        
        if not backup_file.exists():
            self.logger.error(f"PostgreSQL backup file not found: {backup_file}")
            return False
        
        size_mb = backup_file.stat().st_size / (1024 * 1024)
        self.logger.info(f"PostgreSQL backup size: {size_mb:.2f} MB")
        
        if size_mb < 0.1:
            self.logger.warning("PostgreSQL backup file is suspiciously small")
            return False
        
        self.logger.info("PostgreSQL backup validation passed")
        return True
    
    def validate_contentstore_backup(self, timestamp: str) -> bool:
        """Validate contentstore backup exists and has content."""
        if self.config.s3_enabled:
            try:
                from alfresco_backup.utils.s3_utils import check_rclone_installed, get_s3_folder_size
                if not check_rclone_installed():
                    self.logger.error("rclone is not installed. Please install rclone to use S3 restore.")
                    return False
                
                # Validate timestamp format
                try:
                    datetime.strptime(timestamp, '%Y-%m-%d_%H-%M-%S')
                except ValueError:
                    self.logger.error(f"Invalid timestamp format: {timestamp}")
                    return False
                
                # For S3 PITR, we use --s3-version-at which doesn't require exact timestamp match
                # Just verify the contentstore path exists in S3
                s3_path = "alfresco-backups/contentstore/"
                folder_size = get_s3_folder_size(
                    self.config.s3_bucket,
                    s3_path,
                    self.config.s3_access_key_id,
                    self.config.s3_secret_access_key,
                    self.config.s3_region,
                    timeout=30
                )
                
                if folder_size is None:
                    self.logger.error("Could not verify contentstore exists in S3")
                    return False
                
                if folder_size == 0:
                    self.logger.warning("Contentstore path exists in S3 but appears empty")
                    return False
                
                self.logger.info(f"Contentstore backup validated in S3 (size: {folder_size / (1024*1024):.2f} MB)")
                self.logger.info(f"Will restore to timestamp: {timestamp} using S3 versioning")
                return True
            except Exception as e:
                self.logger.error(f"Error validating S3 contentstore backup: {e}")
                return False
        
        backup_dir = Path(self.config.backup_dir) / 'contentstore' / f'contentstore-{timestamp}'
        
        if not backup_dir.exists():
            self.logger.error(f"Contentstore backup directory not found: {backup_dir}")
            return False
        
        try:
            files = list(backup_dir.rglob('*'))
            file_count = sum(1 for f in files if f.is_file())
            
            self.logger.info(f"Contentstore backup contains {file_count} files")
            
            if file_count == 0:
                self.logger.warning("Contentstore backup appears empty")
                return False
            
            dirs = [d for d in backup_dir.iterdir() if d.is_dir()]
            self.logger.info(f"Contentstore backup contains {len(dirs)} top-level directories")
            
        except Exception as e:
            self.logger.error(f"Error validating contentstore backup: {e}")
            return False
        
        self.logger.info("Contentstore backup validation passed")
        return True
    
    def restore_postgres(self, timestamp: str) -> bool:
        """Restore PostgreSQL from backup."""
        self.logger.info(f"Restoring PostgreSQL from backup: {timestamp}")
        
        if self.config.s3_enabled:
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / 'alfresco-restore'
            temp_dir.mkdir(parents=True, exist_ok=True)
            backup_file = temp_dir / f'postgres-{timestamp}.sql.gz'
            
            self.logger.info(f"Downloading PostgreSQL backup from S3...")
            try:
                from alfresco_backup.utils.s3_utils import download_from_s3
                s3_path = f"alfresco-backups/postgres/postgres-{timestamp}.sql.gz"
                download_result = download_from_s3(
                    self.config.s3_bucket,
                    s3_path,
                    backup_file,
                    self.config.s3_access_key_id,
                    self.config.s3_secret_access_key,
                    self.config.s3_region,
                    timeout=3600
                )
                
                if not download_result['success']:
                    self.logger.error(f"Failed to download PostgreSQL backup from S3: {download_result['error']}")
                    return False
                
                self.logger.info(f"PostgreSQL backup downloaded successfully ({download_result['duration']:.1f}s)")
                
                # Verify the downloaded file exists
                # rclone copyto may create a directory with the filename, then put the file inside
                # Check if the path is a directory, and if so, look for the file inside
                if backup_file.is_dir():
                    # rclone created a directory - look for the file inside
                    file_inside = backup_file / backup_file.name
                    if file_inside.exists() and file_inside.is_file():
                        self.logger.info(f"Found file inside directory: {file_inside}")
                        backup_file = file_inside
                    else:
                        # Try to find any .sql.gz file inside
                        sql_files = list(backup_file.glob('*.sql.gz'))
                        if sql_files:
                            self.logger.info(f"Found SQL file in directory: {sql_files[0]}")
                            backup_file = sql_files[0]
                        else:
                            self.logger.error(f"Downloaded backup path is a directory but no file found inside: {backup_file}")
                            self.logger.error("Contents:")
                            for item in backup_file.iterdir():
                                self.logger.error(f"  {item.name} ({'file' if item.is_file() else 'dir'})")
                            return False
                elif not backup_file.exists():
                    self.logger.error(f"Downloaded backup file does not exist: {backup_file}")
                    return False
                elif not backup_file.is_file():
                    self.logger.error(f"Downloaded backup path is not a regular file: {backup_file}")
                    return False
                
            except Exception as e:
                self.logger.error(f"Error downloading PostgreSQL backup from S3: {e}")
                return False
        else:
            backup_file = Path(self.config.backup_dir) / 'postgres' / f'postgres-{timestamp}.sql.gz'
            
            if not backup_file.exists():
                self.logger.error(f"PostgreSQL backup file not found: {backup_file}")
                return False
            
            if backup_file.is_dir():
                self.logger.error(f"Backup path is a directory, not a file: {backup_file}")
                return False
        
        # Load database connection details from .env file
        try:
            import os
            # Try to load .env file
            try:
                from dotenv import load_dotenv
                load_dotenv()
            except ImportError:
                # dotenv not available, try to read .env manually
                try:
                    env_file = Path('.env')
                    if env_file.exists():
                        with open(env_file, 'r') as f:
                            for line in f:
                                line = line.strip()
                                if line and not line.startswith('#') and '=' in line:
                                    key, value = line.split('=', 1)
                                    key = key.strip()
                                    value = value.strip().strip('"').strip("'")
                                    os.environ[key] = value
                except Exception:
                    pass  # Continue with environment variables as-is
            
            pg_host = os.getenv('PGHOST', 'localhost')
            pg_port = os.getenv('PGPORT', '5432')
            pg_user = os.getenv('PGUSER', 'alfresco')
            pg_password = os.getenv('PGPASSWORD')
            pg_database = os.getenv('PGDATABASE', 'postgres')
            
            if not pg_password:
                self.logger.error("PGPASSWORD not found in .env file")
                return False
        except Exception as e:
            self.logger.error(f"Failed to load database configuration: {e}")
            return False
        
        # Use embedded PostgreSQL tools if available
        # Ensure alf_base_dir is a Path object
        alf_base_path = Path(self.config.alf_base_dir) if isinstance(self.config.alf_base_dir, str) else self.config.alf_base_dir
        embedded_psql = alf_base_path / 'postgresql' / 'bin' / 'psql'
        if embedded_psql.exists():
            psql_cmd = str(embedded_psql)
            self.logger.info(f"Using embedded psql: {psql_cmd}")
        else:
            psql_cmd = 'psql'
            self.logger.info(f"Using system psql: {psql_cmd}")
        
        try:
            self.logger.info("Restoring PostgreSQL database from SQL dump...")
            
            # Set PGPASSWORD environment variable
            env = os.environ.copy()
            env['PGPASSWORD'] = pg_password
            
            # Decompress and restore using gunzip piped to psql
            backup_size = backup_file.stat().st_size
            
            with tqdm(total=backup_size, unit='B', unit_scale=True, desc="Restoring PostgreSQL") as pbar:
                # Start gunzip process
                gunzip_process = subprocess.Popen(
                    ['gunzip', '-c', str(backup_file)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                # Start psql process
                psql_process = subprocess.Popen(
                    [psql_cmd, '-h', pg_host, '-p', pg_port, '-U', pg_user, '-d', pg_database],
                    stdin=gunzip_process.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env
                )
                
                # Close gunzip's stdout to allow it to receive SIGPIPE if psql fails
                gunzip_process.stdout.close()
                
                # Read output from psql (this will block until complete)
                stdout, stderr = psql_process.communicate()
                
                # Read gunzip's stderr (it's a file-like object, need to read it)
                gunzip_stderr = b''
                if gunzip_process.stderr:
                    gunzip_stderr = gunzip_process.stderr.read()
                    gunzip_process.stderr.close()
                
                # Wait for gunzip to finish
                gunzip_process.wait()
                
                # Update progress bar
                pbar.update(backup_size)
            
            # Check results
            # Note: gunzip may exit with -13 (SIGPIPE) when psql finishes early, which is normal
            # Only check gunzip if psql failed, or if gunzip failed with a non-SIGPIPE error
            psql_success = psql_process.returncode == 0
            
            # Check if gunzip failed (and it's not a SIGPIPE, which is normal)
            gunzip_failed = gunzip_process.returncode != 0 and gunzip_process.returncode != -13
            if gunzip_failed:
                gunzip_error = gunzip_stderr.decode('utf-8', errors='ignore') if gunzip_stderr else ''
                self.logger.error(f"gunzip failed with code {gunzip_process.returncode}: {gunzip_error}")
                if 'is a directory' in gunzip_error.lower():
                    self.logger.error("Backup file is a directory, not a file. Download may have failed.")
                    return False
            
            if not psql_success:
                # psql failed, check gunzip for additional error info
                if gunzip_process.returncode != 0 and gunzip_process.returncode != -13:
                    # gunzip failed with something other than SIGPIPE
                    error_msg = gunzip_stderr.decode('utf-8', errors='replace') if gunzip_stderr else 'Unknown error'
                    self.logger.error(f"gunzip failed with exit code {gunzip_process.returncode}: {error_msg}")
                
                # Report psql error
                error_msg = stderr.decode('utf-8', errors='replace') if stderr else 'Unknown error'
                stdout_msg = stdout.decode('utf-8', errors='replace') if stdout else ''
                self.logger.error(f"psql failed with exit code {psql_process.returncode}")
                if error_msg:
                    self.logger.error(f"Error: {error_msg}")
                if stdout_msg:
                    self.logger.info(f"Output: {stdout_msg}")
                return False
            
            # psql succeeded, check gunzip only if it's a real error (not SIGPIPE)
            if gunzip_process.returncode != 0 and gunzip_process.returncode != -13:
                # gunzip failed with something other than expected SIGPIPE
                error_msg = gunzip_stderr.decode('utf-8', errors='replace') if gunzip_stderr else 'Unknown error'
                self.logger.warning(f"gunzip exited with code {gunzip_process.returncode}: {error_msg}")
                
                # If gunzip failed because the file is a directory, this is a critical error
                if 'is a directory' in error_msg.lower():
                    self.logger.error("Backup file is a directory, not a file. Restore cannot proceed.")
                    return False
                
                # For other gunzip errors, log warning but don't fail if psql succeeded
                # (psql may have already read all the data before gunzip failed)
            
            self.logger.info("PostgreSQL restore completed successfully")
            
            if self.config.s3_enabled and backup_file.parent.name == 'alfresco-restore':
                try:
                    backup_file.unlink()
                    self.logger.info("Cleaned up temporary downloaded backup file")
                except Exception as e:
                    self.logger.warning(f"Could not clean up temporary file: {e}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"PostgreSQL restore failed: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            
            if self.config.s3_enabled and backup_file.parent.name == 'alfresco-restore':
                try:
                    backup_file.unlink()
                    self.logger.info("Cleaned up temporary downloaded backup file after failure")
                except Exception:
                    pass
            
            return False
    
    def restore_contentstore(self, timestamp: str) -> bool:
        """Restore contentstore from backup."""
        self.logger.info(f"Restoring contentstore from backup: {timestamp}")
        
        if not self.config.contentstore_dir:
            self.logger.error("Contentstore directory not configured")
            return False
        
        if self.config.s3_enabled:
            import tempfile
            from alfresco_backup.utils.s3_utils import download_from_s3, get_s3_version_by_date
            temp_dir = Path(tempfile.gettempdir()) / 'alfresco-restore' / f'contentstore-{timestamp}'
            temp_dir.mkdir(parents=True, exist_ok=True)
            source_dir = temp_dir
            
            self.logger.info(f"Downloading contentstore backup from S3...")
            try:
                target_date = datetime.strptime(timestamp, '%Y-%m-%d_%H-%M-%S')
                version_id = get_s3_version_by_date(
                    self.config.s3_bucket,
                    self.config.s3_access_key_id,
                    self.config.s3_secret_access_key,
                    self.config.s3_region,
                    target_date
                )
                
                if not version_id:
                    self.logger.error(f"No contentstore version found for date: {timestamp}")
                    return False
                
                s3_path = "alfresco-backups/contentstore/"
                download_result = download_from_s3(
                    self.config.s3_bucket,
                    s3_path,
                    source_dir,
                    self.config.s3_access_key_id,
                    self.config.s3_secret_access_key,
                    self.config.s3_region,
                    version_id=version_id,
                    timeout=86400
                )
                
                if not download_result['success']:
                    self.logger.error(f"Failed to download contentstore backup from S3: {download_result['error']}")
                    return False
                
                self.logger.info(f"Contentstore backup downloaded successfully ({download_result['duration']:.1f}s)")
            except Exception as e:
                self.logger.error(f"Error downloading contentstore backup from S3: {e}")
                return False
        else:
            source_dir = Path(self.config.backup_dir) / 'contentstore' / f'contentstore-{timestamp}'
            
            if not source_dir.exists():
                self.logger.error(f"Contentstore backup directory not found: {source_dir}")
                return False
        
        try:
            self.config.contentstore_dir.mkdir(parents=True, exist_ok=True)
            
            self.logger.info("Counting files to copy...")
            file_count = sum(1 for _ in source_dir.rglob('*') if _.is_file())
            
            self.logger.info(f"Copying {file_count} files...")
            
            with tqdm(total=file_count, desc="Copying contentstore", unit=' files') as pbar:
                process = subprocess.Popen(
                    ['sudo', 'rsync', '-av', '--delete', f'{source_dir}/', f'{self.config.contentstore_dir}/'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                for line in process.stdout:
                    if line.strip().endswith('/'):
                        pbar.update(1)
                    elif '/./' in line or '/->' in line:
                        pbar.update(1)
                
                process.wait()
                if process.returncode != 0:
                    raise subprocess.CalledProcessError(process.returncode, 'rsync')
            
            self.logger.info(f"Setting ownership to {self.config.alfresco_user}...")
            subprocess.run(['sudo', 'chown', '-R', f'{self.config.alfresco_user}:{self.config.alfresco_user}', str(self.config.contentstore_dir)], check=True)
            
            self.logger.info("Contentstore restore completed successfully")
            
            if self.config.s3_enabled and source_dir.parent.name == 'alfresco-restore':
                try:
                    import shutil
                    shutil.rmtree(source_dir.parent)
                    self.logger.info("Cleaned up temporary downloaded backup directory")
                except Exception as e:
                    self.logger.warning(f"Could not clean up temporary directory: {e}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Contentstore restore failed: {e}")
            
            if self.config.s3_enabled and 'source_dir' in locals() and source_dir.parent.name == 'alfresco-restore':
                try:
                    import shutil
                    shutil.rmtree(source_dir.parent)
                    self.logger.info("Cleaned up temporary downloaded backup directory after failure")
                except Exception:
                    pass
            
            return False
    
    def restore_contentstore_pitr(self, timestamp: str) -> bool:
        """
        Restore contentstore using S3 versioning to match PostgreSQL backup timestamp.
        
        This enables point-in-time recovery by restoring files to their versions
        at the target timestamp, including files that were deleted after that time.
        
        Args:
            timestamp: PostgreSQL backup timestamp (YYYY-MM-DD_HH-MM-SS format)
        
        Returns:
            True if restore succeeded, False otherwise
        """
        if not self.config.s3_enabled:
            self.logger.error("PITR contentstore restore requires S3 backups with versioning enabled")
            return False
        
        if not self.config.contentstore_dir:
            self.logger.error("Contentstore directory not configured")
            return False
        
        self.logger.info(f"Restoring contentstore to match PostgreSQL backup timestamp: {timestamp}")
        
        try:
            from alfresco_backup.utils.s3_utils import restore_contentstore_from_s3_version
            
            # Parse timestamp and convert to datetime
            target_datetime = datetime.strptime(timestamp, '%Y-%m-%d_%H-%M-%S')
            
            # Restore contentstore using S3 versioning
            self.logger.info("Restoring contentstore files to their versions at target timestamp...")
            self.logger.info("This will restore files that were deleted after the backup timestamp.")
            
            restore_result = restore_contentstore_from_s3_version(
                self.config.s3_bucket,
                "alfresco-backups/contentstore/",
                self.config.contentstore_dir,
                self.config.s3_access_key_id,
                self.config.s3_secret_access_key,
                self.config.s3_region,
                target_datetime,
                timeout=86400  # 24 hours timeout
            )
            
            if not restore_result['success']:
                self.logger.error(f"Failed to restore contentstore from S3: {restore_result['error']}")
                return False
            
            self.logger.info(f"Contentstore restored successfully ({restore_result['duration']:.1f}s)")
            
            # Set ownership
            self.logger.info(f"Setting ownership to {self.config.alfresco_user}...")
            subprocess.run(
                ['sudo', 'chown', '-R', f'{self.config.alfresco_user}:{self.config.alfresco_user}', 
                 str(self.config.contentstore_dir)], 
                check=True
            )
            
            self.logger.info("Contentstore PITR restore completed successfully")
            return True
            
        except ValueError as e:
            self.logger.error(f"Invalid timestamp format: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Contentstore PITR restore failed: {e}")
            return False
    
    def configure_pitr(self, target_time: Optional[str] = None) -> bool:
        """Configure PostgreSQL for point-in-time recovery."""
        if not self.config.postgres_data_dir:
            self.logger.error("PostgreSQL data directory not configured")
            return False
        
        recovery_conf = self.config.postgres_data_dir / 'recovery.conf'
        backup_dir = Path(self.config.backup_dir)
        
        try:
            self.logger.info("Configuring point-in-time recovery...")
            
            recovery_content = f"""# Recovery configuration
restore_command = 'cp {backup_dir}/pg_wal/%f %p'
recovery_target_timeline = 'latest'
"""
            
            if target_time:
                recovery_content += f"recovery_target_time = '{target_time}'\n"
                recovery_content += "recovery_target_action = 'promote'\n"
            
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.conf') as f:
                f.write(recovery_content)
                temp_file = f.name
            
            subprocess.run(['sudo', 'mv', temp_file, str(recovery_conf)], check=True)
            subprocess.run(['sudo', 'chown', f'{self.config.alfresco_user}:{self.config.alfresco_user}', str(recovery_conf)], check=True)
            subprocess.run(['sudo', 'chmod', '600', str(recovery_conf)], check=True)
            
            self.logger.info("Point-in-time recovery configured")
            if target_time:
                self.logger.info(f"Recovery target time: {target_time}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error configuring PITR: {e}")
            return False
    
    def list_wal_files(self) -> List[str]:
        """List available WAL files for PITR."""
        wal_dir = Path(self.config.backup_dir) / 'pg_wal'
        
        if not wal_dir.exists():
            return []
        
        wal_files = []
        for item in wal_dir.iterdir():
            if item.is_file() and item.name.startswith('0'):
                wal_files.append(item.name)
        
        return sorted(wal_files)
    
    def estimate_pitr_restore_time(self, target_time: Optional[str] = None) -> Optional[datetime]:
        """Estimate recovery time based on WAL files."""
        if not target_time:
            return None
        
        wal_files = self.list_wal_files()
        if not wal_files:
            return None
        
        try:
            target = datetime.strptime(target_time, '%Y-%m-%d %H:%M:%S')
            self.logger.info(f"Analyzing {len(wal_files)} WAL files for recovery to {target}")
            return target
        except ValueError:
            self.logger.error(f"Invalid target time format: {target_time}")
            return None
    
    def start_tomcat_only(self) -> bool:
        """Start only Tomcat (PostgreSQL should already be running)."""
        self.logger.info("Starting Tomcat only (PostgreSQL should already be running)...")
        
        try:
            # Try to start tomcat using alfresco.sh start-tomcat or similar
            result = subprocess.run(
                ['sudo', '-u', self.config.alfresco_user, 
                 str(self.config.alfresco_script), 'start-tomcat'],
                capture_output=True,
                text=True,
                timeout=600
            )
            
            if result.returncode == 0:
                self.logger.info("Tomcat started successfully")
                self.logger.info("Monitor startup with: tail -f {}/tomcat/logs/catalina.out".format(self.config.alf_base_dir))
                return True
            else:
                # Fallback: use regular start (it should skip PostgreSQL if already running)
                self.logger.info("Attempting to start via alfresco.sh start (PostgreSQL should remain running)...")
                return self.start_alfresco()
                
        except subprocess.TimeoutExpired:
            self.logger.error("Tomcat start timed out")
            return False
        except Exception as e:
            self.logger.error(f"Error starting Tomcat: {e}")
            return False
    
    def start_alfresco(self) -> bool:
        """Start Alfresco services."""
        self.logger.info("Starting Alfresco services...")
        
        try:
            result = subprocess.run(
                ['sudo', '-u', self.config.alfresco_user, str(self.config.alfresco_script), 'start'],
                capture_output=True, text=True, timeout=600
            )
            
            if result.returncode == 0:
                self.logger.info("Alfresco services started successfully")
                self.logger.info("Monitor startup with: tail -f {}/tomcat/logs/catalina.out".format(self.config.alf_base_dir))
                return True
            else:
                self.logger.error(f"Alfresco start failed: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error starting Alfresco: {e}")
            return False


def ask_question(prompt: str, default: Optional[str] = None) -> str:
    """Ask user a question and return their answer."""
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
    
    while True:
        answer = input(prompt).strip()
        if answer:
            return answer
        if default:
            return default
        print("This field is required. Please enter a value.")
def get_config() -> RestoreConfig:
    """Load restore configuration from .env file or interactively collect from user."""
    config = RestoreConfig()
    
    # Track what was loaded from .env to avoid re-prompting
    # Initialize outside try block so it's available in interactive section
    env_loaded = {
        'backup_dir': False,
        'alf_base_dir': False,
        'alfresco_user': False,
        's3_bucket': False,
        's3_region': False,
        's3_access_key_id': False,
        's3_secret_access_key': False
    }
    
    # Variables to hold .env values for use in interactive section
    backup_dir = None
    alf_base_dir = None
    alfresco_user = None
    s3_bucket = None
    
    # Try to load from .env file first
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        backup_dir = os.getenv('BACKUP_DIR')
        alf_base_dir = os.getenv('ALF_BASE_DIR')
        alfresco_user = os.getenv('ALFRESCO_USER')
        s3_bucket = os.getenv('S3_BUCKET')
        
        # Store values for use in interactive section
        
        if backup_dir:
            env_loaded['backup_dir'] = True
        if alf_base_dir:
            env_loaded['alf_base_dir'] = True
        if alfresco_user:
            env_loaded['alfresco_user'] = True
        
        if s3_bucket:
            config.s3_enabled = True
            config.s3_bucket = s3_bucket
            env_loaded['s3_bucket'] = True
            config.s3_region = os.getenv('S3_REGION', 'us-east-1')
            if os.getenv('S3_REGION'):
                env_loaded['s3_region'] = True
            config.s3_access_key_id = os.getenv('AWS_ACCESS_KEY_ID', '')
            if os.getenv('AWS_ACCESS_KEY_ID'):
                env_loaded['s3_access_key_id'] = True
            config.s3_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY', '')
            if os.getenv('AWS_SECRET_ACCESS_KEY'):
                env_loaded['s3_secret_access_key'] = True
        
        # Check if we have enough configuration to proceed
        # For S3 mode: need alf_base_dir and S3 credentials
        # For local mode: need backup_dir and alf_base_dir
        if config.s3_enabled:
            if alf_base_dir and Path(alf_base_dir).exists():
                if config.s3_bucket and config.s3_access_key_id and config.s3_secret_access_key:
                    config.alf_base_dir = Path(alf_base_dir)
                    config.alfresco_user = alfresco_user or config.alfresco_user
                    config.restore_log_dir = str(Path.cwd())
                    print("\nConfiguration loaded from .env file (S3 mode)")
                    return config
        elif backup_dir and alf_base_dir:
            if Path(backup_dir).exists() and Path(alf_base_dir).exists():
                config.backup_dir = backup_dir
                config.alf_base_dir = Path(alf_base_dir)
                config.alfresco_user = alfresco_user or config.alfresco_user
                config.restore_log_dir = str(Path.cwd())
                print("\nConfiguration loaded from .env file (local mode)")
                return config
        
        # If we get here, some configuration is missing
        if config.s3_enabled or backup_dir or s3_bucket or alf_base_dir:
            print("\nWarning: .env file found but some configuration is invalid, prompting for missing values...")
    except ImportError:
        # dotenv not available, try to load .env manually or continue with interactive
        try:
            # Try to read .env file directly
            env_file = Path('.env')
            if env_file.exists():
                with open(env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            os.environ[key] = value
                            # Set config values if relevant
                            if key == 'S3_BUCKET' and value:
                                config.s3_enabled = True
                                config.s3_bucket = value
                                env_loaded['s3_bucket'] = True
                                s3_bucket = value
                            elif key == 'S3_REGION' and value:
                                config.s3_region = value
                                env_loaded['s3_region'] = True
                            elif key == 'AWS_ACCESS_KEY_ID' and value:
                                config.s3_access_key_id = value
                                env_loaded['s3_access_key_id'] = True
                            elif key == 'AWS_SECRET_ACCESS_KEY' and value:
                                config.s3_secret_access_key = value
                                env_loaded['s3_secret_access_key'] = True
                            elif key == 'ALF_BASE_DIR' and value:
                                alf_base_dir = value
                                env_loaded['alf_base_dir'] = True
                            elif key == 'ALFRESCO_USER' and value:
                                alfresco_user = value
                                env_loaded['alfresco_user'] = True
                            elif key == 'BACKUP_DIR' and value:
                                backup_dir = value
                                env_loaded['backup_dir'] = True
                
                # After manual parsing, check if we have complete config for early return
                if config.s3_enabled:
                    if alf_base_dir and Path(alf_base_dir).exists():
                        if config.s3_bucket and config.s3_access_key_id and config.s3_secret_access_key:
                            config.alf_base_dir = Path(alf_base_dir)
                            config.alfresco_user = alfresco_user or config.alfresco_user
                            config.restore_log_dir = str(Path.cwd())
                            print("\nConfiguration loaded from .env file (S3 mode)")
                            return config
        except Exception:
            pass  # Failed to read .env, continue with interactive
    except Exception as e:
        print(f"\nWarning: Could not load .env file: {e}, prompting for configuration...")
    
    # Fall back to interactive configuration
    print("\n" + "=" * 80)
    print("  Alfresco Restore Configuration")
    print("=" * 80)
    print("\nPlease provide the following information:\n")
    
    # Determine backup location type
    # Check environment variables directly as fallback (in case .env loading failed)
    s3_bucket_from_env = os.getenv('S3_BUCKET') or s3_bucket
    if s3_bucket_from_env and not config.s3_enabled:
        config.s3_enabled = True
        config.s3_bucket = s3_bucket_from_env
        env_loaded['s3_bucket'] = True
    
    # If S3_BUCKET is in .env, S3 is already enabled - skip location prompt
    if config.s3_enabled or env_loaded.get('s3_bucket', False) or s3_bucket_from_env:
        # S3 is enabled (from .env or will be), prompt only for missing S3 credentials
        if not env_loaded.get('s3_bucket', False):
            config.s3_bucket = ask_question("S3 bucket name (S3_BUCKET)")
        elif s3_bucket:
            config.s3_bucket = s3_bucket
        elif config.s3_bucket:
            pass  # Already set
        else:
            config.s3_bucket = os.getenv('S3_BUCKET', '')
        
        if not env_loaded.get('s3_region', False):
            config.s3_region = ask_question("S3 region (S3_REGION)", config.s3_region or "us-east-1")
        elif not config.s3_region:
            config.s3_region = os.getenv('S3_REGION', 'us-east-1')
        
        if not env_loaded.get('s3_access_key_id', False):
            config.s3_access_key_id = ask_question("AWS Access Key ID (AWS_ACCESS_KEY_ID)")
        elif not config.s3_access_key_id:
            config.s3_access_key_id = os.getenv('AWS_ACCESS_KEY_ID', '')
        
        if not env_loaded.get('s3_secret_access_key', False):
            config.s3_secret_access_key = ask_question("AWS Secret Access Key (AWS_SECRET_ACCESS_KEY)")
        elif not config.s3_secret_access_key:
            config.s3_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY', '')
        
        # Ensure s3_enabled is set
        config.s3_enabled = True
    else:
        # No S3 config in .env, ask user to choose
        print("Backup location:")
        print("  1. Local directory")
        print("  2. S3 bucket")
        backup_location = input("Select backup location (1 or 2) [1]: ").strip() or '1'
        
        if backup_location == '2':
            config.s3_enabled = True
            config.s3_bucket = ask_question("S3 bucket name (S3_BUCKET)")
            config.s3_region = ask_question("S3 region (S3_REGION)", "us-east-1")
            config.s3_access_key_id = ask_question("AWS Access Key ID (AWS_ACCESS_KEY_ID)")
            config.s3_secret_access_key = ask_question("AWS Secret Access Key (AWS_SECRET_ACCESS_KEY)")
        else:
            # Local backup directory
            if not env_loaded.get('backup_dir', False):
                while True:
                    backup_dir_input = ask_question("Backup directory path (BACKUP_DIR)")
                    if Path(backup_dir_input).exists():
                        config.backup_dir = backup_dir_input
                        break
                    print(f"Error: Directory does not exist: {backup_dir_input}\n")
            elif backup_dir:
                config.backup_dir = backup_dir
    
    # Only prompt for alf_base_dir if not already set from .env
    if not env_loaded.get('alf_base_dir', False):
        while True:
            alf_base = ask_question("Alfresco base directory (ALF_BASE_DIR)")
            alf_base_path = Path(alf_base)
            if alf_base_path.exists():
                config.alf_base_dir = alf_base_path
                break
            print(f"Error: Directory does not exist: {alf_base}\n")
    elif alf_base_dir and Path(alf_base_dir).exists():
        config.alf_base_dir = Path(alf_base_dir)
    
    # Only prompt for alfresco_user if not already set from .env
    if not env_loaded.get('alfresco_user', False):
        config.alfresco_user = ask_question("Alfresco username", config.alfresco_user)
    elif alfresco_user:
        config.alfresco_user = alfresco_user
    
    # Only prompt for log_dir if not already set
    if not config.restore_log_dir:
        log_dir = ask_question("Log file directory", str(Path.cwd()))
        config.restore_log_dir = log_dir
    
    return config


def select_backup(backups: List[str], backup_type: str) -> str:
    """Allow user to select a backup from a list."""
    if not backups:
        print(f"\nNo {backup_type} backups found!")
        return None
    
    print(f"\nAvailable {backup_type} backups:")
    print("-" * 80)
    for i, backup in enumerate(backups[:20], 1):
        print(f"  {i}. {backup}")
    
    if len(backups) > 20:
        print(f"  ... and {len(backups) - 20} older backups")
    
    while True:
        choice = input(f"\nSelect {backup_type} backup (1-{min(len(backups), 20)}): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < min(len(backups), 20):
                return backups[idx]
            print(f"Please enter a number between 1 and {min(len(backups), 20)}")
        except ValueError:
            print("Please enter a valid number")
def main():
    """Main restore program."""
    parser = ArgumentParser(description='Alfresco automated restore system')
    args = parser.parse_args()
    
    config = get_config()
    
    success, errors = config.validate()
    if not success:
        print("\nConfiguration validation failed:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    
    log_file = Path(config.restore_log_dir) / f'restore-{datetime.now().strftime("%Y%m%d-%H%M%S")}.log'
    logger = RestoreLogger(log_file)
    
    logger.section("Alfresco Restore Started")
    logger.info(f"Configuration:")
    logger.info(f"  Backup directory: {config.backup_dir}")
    logger.info(f"  Alfresco base directory: {config.alf_base_dir}")
    logger.info(f"  Alfresco user: {config.alfresco_user}")
    logger.info(f"  Log file: {log_file}")
    
    print("\n" + "=" * 80)
    print("  Restore Mode Selection")
    print("=" * 80)
    print("\nSelect restore mode:")
    print("  1. Full system restore (PostgreSQL + Contentstore)")
    print("  2. Point-in-Time Recovery (PITR)")
    print("  3. PostgreSQL only")
    print("  4. Contentstore only")
    
    while True:
        choice = input("\nEnter choice (1-4): ").strip()
        if choice in ['1', '2', '3', '4']:
            restore_mode = int(choice)
            break
        print("Please enter 1, 2, 3, or 4")
    
    logger.info(f"Restore mode: {restore_mode}")
    
    restore = AlfrescoRestore(config, logger)
    
    try:
        if restore_mode == 1:
            logger.section("Full System Restore")
            
            pg_backups = restore.list_postgres_backups()
            
            if not pg_backups:
                logger.error("No PostgreSQL backups found for full system restore")
                sys.exit(1)
            
            if config.s3_enabled:
                cs_backups = pg_backups
                logger.info("S3 mode: Using PostgreSQL backup timestamps for contentstore restore")
            else:
                cs_backups = restore.list_contentstore_backups()
                if not cs_backups:
                    logger.error("No contentstore backups found for full system restore")
                    sys.exit(1)
            
            pg_timestamp = select_backup(pg_backups, "PostgreSQL")
            if not pg_timestamp:
                logger.error("No PostgreSQL backup selected")
                sys.exit(1)
            
            if config.s3_enabled:
                cs_timestamp = pg_timestamp
                logger.info("S3 mode: Contentstore will be restored to match PostgreSQL backup timestamp")
            else:
                cs_timestamp = select_backup(cs_backups, "Contentstore")
                if not cs_timestamp:
                    logger.error("No contentstore backup selected")
                    sys.exit(1)
            
            logger.info(f"Selected PostgreSQL backup: {pg_timestamp}")
            logger.info(f"Selected Contentstore backup: {cs_timestamp}")
            
            logger.section("Validating Backups")
            if not restore.validate_postgres_backup(pg_timestamp):
                logger.error("PostgreSQL backup validation failed")
                sys.exit(1)
            
            if not restore.validate_contentstore_backup(cs_timestamp):
                logger.error("Contentstore backup validation failed")
                sys.exit(1)
            
            logger.section("Restore Confirmation")
            logger.info("About to restore:")
            logger.info(f"  PostgreSQL: {pg_timestamp}")
            logger.info(f"  Contentstore: {cs_timestamp}")
            logger.info("")
            logger.warning("WARNING: This will replace current data!")
            logger.warning("Current data will be backed up automatically.")
            logger.warning("PostgreSQL must be running for database restore.")
            logger.info("")
            
            confirm = input("Type 'RESTORE' to confirm: ").strip()
            if confirm != 'RESTORE':
                logger.info("Restore cancelled by user")
                sys.exit(0)
            
            # Step 1: Start all Alfresco services (including PostgreSQL)
            logger.section("Starting Alfresco Services")
            if not restore.start_alfresco_full():
                logger.error("Failed to start Alfresco services")
                sys.exit(1)
            
            # Step 2: Wait 2 minutes for services to fully start
            logger.section("Waiting for Services to Start")
            logger.info("Waiting 2 minutes for Alfresco services to fully initialize...")
            import time
            time.sleep(120)  # 2 minutes
            logger.info("Wait completed")
            
            # Step 3: Stop only Tomcat (PostgreSQL must remain running)
            logger.section("Stopping Tomcat")
            if not restore.stop_tomcat_only():
                logger.error("Failed to stop Tomcat")
                sys.exit(1)
            
            # Step 4: Verify PostgreSQL is running
            logger.section("Verifying PostgreSQL")
            if not restore.verify_postgresql_running():
                logger.error("PostgreSQL is not running or not accepting connections")
                logger.error("Cannot proceed with database restore")
                sys.exit(1)
            
            # Step 5: Backup current data
            logger.section("Backing Up Current Data")
            success, backup_timestamp = restore.backup_current_data()
            if not success:
                logger.error("Failed to backup current data")
                sys.exit(1)
            logger.info(f"Current data backed up with timestamp: {backup_timestamp}")
            
            # Step 6: Restore PostgreSQL
            logger.section("Restoring PostgreSQL")
            if not restore.restore_postgres(pg_timestamp):
                logger.error("PostgreSQL restore failed")
                sys.exit(1)
            
            # Step 7: Restore Contentstore
            logger.section("Restoring Contentstore")
            if config.s3_enabled:
                if not restore.restore_contentstore_pitr(cs_timestamp):
                    logger.error("Contentstore restore failed")
                    sys.exit(1)
            else:
                if not restore.restore_contentstore(cs_timestamp):
                    logger.error("Contentstore restore failed")
                    sys.exit(1)
            
            # Step 8: Start Tomcat (PostgreSQL is already running)
            logger.section("Starting Tomcat")
            if not restore.start_tomcat_only():
                logger.error("Failed to start Tomcat")
                logger.info("Tomcat may need manual intervention to start")
            
            logger.section("Restore Complete")
            logger.info("Full system restore completed successfully!")
            logger.info(f"Backup log: {log_file}")
        
        elif restore_mode == 2:
            logger.section("Point-in-Time Recovery")
            
            # PITR requires S3 backups with versioning enabled
            if not config.s3_enabled:
                logger.error("Point-in-Time Recovery (PITR) requires S3 backups with versioning enabled.")
                logger.error("PITR is not available for local backups.")
                logger.info("")
                logger.info("To use PITR, configure S3 backups with versioning enabled.")
                logger.info("For local backups, use option 1 (Full system restore) instead.")
                sys.exit(1)
            
            logger.info("Point-in-Time Recovery (PITR) mode")
            logger.info("This will restore PostgreSQL from a selected backup and restore contentstore")
            logger.info("to match that timestamp using S3 versioning (including deleted files).")
            logger.info("")
            
            # List PostgreSQL backups
            pg_backups = restore.list_postgres_backups()
            if not pg_backups:
                logger.error("No PostgreSQL backups found in S3")
                sys.exit(1)
            
            # Show available backups with timestamps
            logger.info("Available PostgreSQL backups:")
            logger.info("-" * 80)
            for i, backup in enumerate(pg_backups[:20], 1):
                logger.info(f"  {i}. {backup}")
            if len(pg_backups) > 20:
                logger.info(f"  ... and {len(pg_backups) - 20} older backups")
            
            # User selects backup
            pg_timestamp = select_backup(pg_backups, "PostgreSQL")
            if not pg_timestamp:
                logger.error("No PostgreSQL backup selected")
                sys.exit(1)
            
            logger.info(f"Selected PostgreSQL backup: {pg_timestamp}")
            
            # Validate backup
            logger.section("Validating Backup")
            if not restore.validate_postgres_backup(pg_timestamp):
                logger.error("PostgreSQL backup validation failed")
                sys.exit(1)
            
            # Confirmation
            logger.section("Restore Confirmation")
            logger.info("About to restore:")
            logger.info(f"  PostgreSQL: {pg_timestamp}")
            logger.info(f"  Contentstore: Will be restored to match PostgreSQL backup timestamp using S3 versioning")
            logger.info("")
            logger.warning("WARNING: This will replace current data!")
            logger.warning("Current data will be backed up automatically.")
            logger.warning("PostgreSQL must be running for database restore.")
            logger.info("")
            
            confirm = input("Type 'RESTORE' to confirm: ").strip()
            if confirm != 'RESTORE':
                logger.info("Restore cancelled by user")
                sys.exit(0)
            
            # Step 1: Start all Alfresco services (including PostgreSQL)
            logger.section("Starting Alfresco Services")
            if not restore.start_alfresco_full():
                logger.error("Failed to start Alfresco services")
                sys.exit(1)
            
            # Step 2: Wait 2 minutes for services to fully start
            logger.section("Waiting for Services to Start")
            logger.info("Waiting 2 minutes for Alfresco services to fully initialize...")
            import time
            time.sleep(120)  # 2 minutes
            logger.info("Wait completed")
            
            # Step 3: Stop only Tomcat (PostgreSQL must remain running)
            logger.section("Stopping Tomcat")
            if not restore.stop_tomcat_only():
                logger.error("Failed to stop Tomcat")
                sys.exit(1)
            
            # Step 4: Verify PostgreSQL is running
            logger.section("Verifying PostgreSQL")
            if not restore.verify_postgresql_running():
                logger.error("PostgreSQL is not running or not accepting connections")
                logger.error("Cannot proceed with database restore")
                sys.exit(1)
            
            # Step 5: Backup current data
            logger.section("Backing Up Current Data")
            success, backup_timestamp = restore.backup_current_data()
            if not success:
                logger.error("Failed to backup current data")
                sys.exit(1)
            logger.info(f"Current data backed up with timestamp: {backup_timestamp}")
            
            # Step 6: Restore PostgreSQL
            logger.section("Restoring PostgreSQL")
            if not restore.restore_postgres(pg_timestamp):
                logger.error("PostgreSQL restore failed")
                sys.exit(1)
            
            # Step 7: Restore Contentstore using PITR (S3 versioning)
            logger.section("Restoring Contentstore (PITR)")
            logger.info("Restoring contentstore to match PostgreSQL backup timestamp using S3 versioning...")
            if not restore.restore_contentstore_pitr(pg_timestamp):
                logger.error("Contentstore PITR restore failed")
                sys.exit(1)
            
            # Step 8: Start Tomcat (PostgreSQL is already running)
            logger.section("Starting Tomcat")
            if not restore.start_tomcat_only():
                logger.error("Failed to start Tomcat")
                logger.info("Tomcat may need manual intervention to start")
            
            logger.section("PITR Restore Complete")
            logger.info("Point-in-time recovery completed successfully!")
            logger.info(f"PostgreSQL restored from backup: {pg_timestamp}")
            logger.info(f"Contentstore restored to match PostgreSQL backup timestamp using S3 versioning")
            logger.info(f"Backup log: {log_file}")
        
        elif restore_mode == 3:
            logger.section("PostgreSQL Only Restore")
            
            pg_backups = restore.list_postgres_backups()
            if not pg_backups:
                logger.error("No PostgreSQL backups found")
                sys.exit(1)
            
            pg_timestamp = select_backup(pg_backups, "PostgreSQL")
            if not pg_timestamp:
                logger.error("No backup selected")
                sys.exit(1)
            
            if not restore.validate_postgres_backup(pg_timestamp):
                logger.error("PostgreSQL backup validation failed")
                sys.exit(1)
            
            logger.section("Restore Confirmation")
            logger.info("About to restore PostgreSQL:")
            logger.info(f"  PostgreSQL: {pg_timestamp}")
            logger.info("")
            logger.warning("WARNING: This will replace current PostgreSQL data!")
            logger.warning("Current data will be backed up automatically.")
            logger.warning("PostgreSQL must be running for database restore.")
            logger.info("")
            
            confirm = input("Type 'RESTORE' to confirm: ").strip()
            if confirm != 'RESTORE':
                logger.info("Restore cancelled by user")
                sys.exit(0)
            
            # Step 1: Start all Alfresco services (including PostgreSQL)
            logger.section("Starting Alfresco Services")
            if not restore.start_alfresco_full():
                logger.error("Failed to start Alfresco services")
                sys.exit(1)
            
            # Step 2: Wait 2 minutes for services to fully start
            logger.section("Waiting for Services to Start")
            logger.info("Waiting 2 minutes for Alfresco services to fully initialize...")
            import time
            time.sleep(120)  # 2 minutes
            logger.info("Wait completed")
            
            # Step 3: Stop only Tomcat (PostgreSQL must remain running)
            logger.section("Stopping Tomcat")
            if not restore.stop_tomcat_only():
                logger.error("Failed to stop Tomcat")
                sys.exit(1)
            
            # Step 4: Verify PostgreSQL is running
            logger.section("Verifying PostgreSQL")
            if not restore.verify_postgresql_running():
                logger.error("PostgreSQL is not running or not accepting connections")
                logger.error("Cannot proceed with database restore")
                sys.exit(1)
            
            # Step 5: Backup current data
            logger.section("Backing Up Current Data")
            success, backup_timestamp = restore.backup_current_data()
            if not success:
                logger.error("Failed to backup current data")
                sys.exit(1)
            logger.info(f"Current data backed up with timestamp: {backup_timestamp}")
            
            # Step 6: Restore PostgreSQL
            logger.section("Restoring PostgreSQL")
            if not restore.restore_postgres(pg_timestamp):
                logger.error("PostgreSQL restore failed")
                sys.exit(1)
            
            # Step 7: Start Tomcat (PostgreSQL is already running)
            logger.section("Starting Tomcat")
            if not restore.start_tomcat_only():
                logger.error("Failed to start Tomcat")
                logger.info("Tomcat may need manual intervention to start")
            
            logger.section("Restore Complete")
            logger.info("PostgreSQL restore completed successfully!")
            logger.info(f"Backup log: {log_file}")
        
        elif restore_mode == 4:
            logger.section("Contentstore Only Restore")
            logger.error("Contentstore-only mode not yet fully implemented")
            sys.exit(1)
    
    except KeyboardInterrupt:
        logger.warning("\nRestore interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
