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
        self.alfresco_user = 'evadm'
        self.backup_dir = None
        self.alf_base_dir = None
        self.postgres_data_dir = None
        self.contentstore_dir = None
        self.alfresco_script = None
        self.restore_log_dir = None
        
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate configuration and return (success, errors)."""
        errors = []
        
        if not self.backup_dir or not Path(self.backup_dir).exists():
            errors.append(f"Backup directory does not exist: {self.backup_dir}")
        
        if not self.alf_base_dir or not Path(self.alf_base_dir).exists():
            errors.append(f"Alfresco base directory does not exist: {self.alf_base_dir}")
        
        if self.alf_base_dir:
            pg_root = Path(self.alf_base_dir) / 'alf_data' / 'postgresql'
            pg_data_candidate = pg_root / 'data'
            if (pg_root / 'PG_VERSION').exists():
                self.postgres_data_dir = pg_root
            elif (pg_data_candidate / 'PG_VERSION').exists():
                self.postgres_data_dir = pg_data_candidate
            else:
                self.postgres_data_dir = pg_root

            self.contentstore_dir = Path(self.alf_base_dir) / 'alf_data' / 'contentstore'
            self.alfresco_script = Path(self.alf_base_dir) / 'alfresco.sh'
            
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
    
    def error(self, message: str):
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
        
    def stop_alfresco(self) -> bool:
        """Stop Alfresco and PostgreSQL services."""
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
        backup_dir = Path(self.config.backup_dir) / 'postgres'
        if not backup_dir.exists():
            return []
        
        backups = []
        for item in backup_dir.iterdir():
            if item.is_dir() and item.name.startswith('base-'):
                timestamp = item.name.replace('base-', '')
                backups.append(timestamp)
        
        return sorted(backups, reverse=True)
    
    def list_contentstore_backups(self) -> List[str]:
        """List available contentstore backups."""
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
        backup_dir = Path(self.config.backup_dir) / 'postgres' / f'base-{timestamp}'
        
        if not backup_dir.exists():
            self.logger.error(f"PostgreSQL backup directory not found: {backup_dir}")
            return False
        
        base_tar = backup_dir / 'base.tar.gz'
        if not base_tar.exists():
            self.logger.error(f"PostgreSQL backup file not found: {base_tar}")
            return False
        
        size_mb = base_tar.stat().st_size / (1024 * 1024)
        self.logger.info(f"PostgreSQL backup size: {size_mb:.2f} MB")
        
        if size_mb < 1:
            self.logger.warning("PostgreSQL backup file is suspiciously small")
            return False
        
        self.logger.info("PostgreSQL backup validation passed")
        return True
    
    def validate_contentstore_backup(self, timestamp: str) -> bool:
        """Validate contentstore backup exists and has content."""
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
        
        backup_dir = Path(self.config.backup_dir) / 'postgres' / f'base-{timestamp}'
        base_tar = backup_dir / 'base.tar.gz'
        
        if not self.config.postgres_data_dir:
            self.logger.error("PostgreSQL data directory not configured")
            return False
        
        try:
            if self.config.postgres_data_dir.exists():
                subprocess.run(['sudo', 'rm', '-rf', str(self.config.postgres_data_dir)], check=True)
            self.config.postgres_data_dir.mkdir(parents=True, exist_ok=True)
            
            self.logger.info("Extracting PostgreSQL backup...")
            
            tar_size = base_tar.stat().st_size
            with tqdm(total=tar_size, unit='B', unit_scale=True, desc="Extracting PostgreSQL") as pbar:
                process = subprocess.Popen(
                    ['sudo', 'tar', '-xzf', str(base_tar), '-C', str(self.config.postgres_data_dir)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                while True:
                    chunk = process.stdout.read(1024)
                    if not chunk:
                        break
                    pbar.update(len(chunk))
                
                process.wait()
                if process.returncode != 0:
                    raise subprocess.CalledProcessError(process.returncode, 'tar')
            
            self.logger.info(f"Setting ownership to {self.config.alfresco_user}...")
            subprocess.run(['sudo', 'chown', '-R', f'{self.config.alfresco_user}:{self.config.alfresco_user}', str(self.config.postgres_data_dir)], check=True)
            subprocess.run(['sudo', 'chmod', '700', str(self.config.postgres_data_dir)], check=True)
            
            self.logger.info("PostgreSQL restore completed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"PostgreSQL restore failed: {e}")
            return False
    
    def restore_contentstore(self, timestamp: str) -> bool:
        """Restore contentstore from backup."""
        self.logger.info(f"Restoring contentstore from backup: {timestamp}")
        
        source_dir = Path(self.config.backup_dir) / 'contentstore' / f'contentstore-{timestamp}'
        
        if not self.config.contentstore_dir:
            self.logger.error("Contentstore directory not configured")
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
            return True
            
        except Exception as e:
            self.logger.error(f"Contentstore restore failed: {e}")
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
    """Interactively collect restore configuration from user."""
    config = RestoreConfig()
    
    print("\n" + "=" * 80)
    print("  Alfresco Restore Configuration")
    print("=" * 80)
    print("\nPlease provide the following information:\n")
    
    while True:
        backup_dir = ask_question("Backup directory path (BACKUP_DIR)")
        if Path(backup_dir).exists():
            config.backup_dir = backup_dir
            break
        print(f"Error: Directory does not exist: {backup_dir}\n")
    
    while True:
        alf_base = ask_question("Alfresco base directory (ALF_BASE_DIR)")
        if Path(alf_base).exists():
            config.alf_base_dir = alf_base
            break
        print(f"Error: Directory does not exist: {alf_base}\n")
    
    config.alfresco_user = ask_question("Alfresco username", config.alfresco_user)
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
            cs_backups = restore.list_contentstore_backups()
            
            if not pg_backups or not cs_backups:
                logger.error("No backups found for full system restore")
                sys.exit(1)
            
            pg_timestamp = select_backup(pg_backups, "PostgreSQL")
            if not pg_timestamp:
                logger.error("No PostgreSQL backup selected")
                sys.exit(1)
            
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
            logger.warning("WARNING: This will stop Alfresco and replace current data!")
            logger.warning("Current data will be backed up automatically.")
            logger.info("")
            
            confirm = input("Type 'RESTORE' to confirm: ").strip()
            if confirm != 'RESTORE':
                logger.info("Restore cancelled by user")
                sys.exit(0)
            
            logger.section("Stopping Alfresco")
            if not restore.stop_alfresco():
                logger.error("Failed to stop Alfresco")
                sys.exit(1)
            
            restore.verify_stopped()
            
            logger.section("Backing Up Current Data")
            success, backup_timestamp = restore.backup_current_data()
            if not success:
                logger.error("Failed to backup current data")
                sys.exit(1)
            logger.info(f"Current data backed up with timestamp: {backup_timestamp}")
            
            logger.section("Restoring PostgreSQL")
            if not restore.restore_postgres(pg_timestamp):
                logger.error("PostgreSQL restore failed")
                sys.exit(1)
            
            logger.section("Restoring Contentstore")
            if not restore.restore_contentstore(cs_timestamp):
                logger.error("Contentstore restore failed")
                sys.exit(1)
            
            logger.section("Starting Alfresco")
            if not restore.start_alfresco():
                logger.error("Failed to start Alfresco")
                logger.info("Alfresco may need manual intervention to start")
            
            logger.section("Restore Complete")
            logger.info("Full system restore completed successfully!")
            logger.info(f"Backup log: {log_file}")
        
        elif restore_mode == 2:
            logger.section("Point-in-Time Recovery")
            
            pg_backups = restore.list_postgres_backups()
            cs_backups = restore.list_contentstore_backups()
            
            if not pg_backups:
                logger.error("No PostgreSQL backups found")
                sys.exit(1)
            
            wal_files = restore.list_wal_files()
            logger.info(f"Found {len(wal_files)} WAL files for recovery")
            
            pg_timestamp = select_backup(pg_backups, "PostgreSQL base backup")
            if not pg_timestamp:
                logger.error("No PostgreSQL backup selected")
                sys.exit(1)
            
            logger.info(f"Selected PostgreSQL backup: {pg_timestamp}")
            
            while True:
                target_time = input("\nEnter target recovery time (YYYY-MM-DD HH:MM:SS) or press Enter for latest: ").strip()
                if not target_time:
                    target_time = None
                    logger.info("Recovering to latest available time")
                    break
                try:
                    datetime.strptime(target_time, '%Y-%m-%d %H:%M:%S')
                    break
                except ValueError:
                    print("Invalid format. Please use YYYY-MM-DD HH:MM:SS")
            
            logger.section("Validating Backup")
            if not restore.validate_postgres_backup(pg_timestamp):
                logger.error("PostgreSQL backup validation failed")
                sys.exit(1)
            
            logger.section("Restore Confirmation")
            logger.info("About to perform PITR:")
            logger.info(f"  Base backup: {pg_timestamp}")
            if target_time:
                logger.info(f"  Recovery target: {target_time}")
            else:
                logger.info(f"  Recovery target: Latest available")
            logger.info("")
            logger.warning("WARNING: This will stop Alfresco and replace current data!")
            logger.warning("Current data will be backed up automatically.")
            logger.info("")
            
            confirm = input("Type 'RESTORE' to confirm: ").strip()
            if confirm != 'RESTORE':
                logger.info("Restore cancelled by user")
                sys.exit(0)
            
            logger.section("Stopping Alfresco")
            if not restore.stop_alfresco():
                logger.error("Failed to stop Alfresco")
                sys.exit(1)
            
            restore.verify_stopped()
            
            logger.section("Backing Up Current Data")
            success, backup_timestamp = restore.backup_current_data()
            if not success:
                logger.error("Failed to backup current data")
                sys.exit(1)
            logger.info(f"Current data backed up with timestamp: {backup_timestamp}")
            
            logger.section("Restoring PostgreSQL Base Backup")
            if not restore.restore_postgres(pg_timestamp):
                logger.error("PostgreSQL restore failed")
                sys.exit(1)
            
            logger.section("Configuring PITR")
            if not restore.configure_pitr(target_time):
                logger.error("Failed to configure PITR")
                sys.exit(1)
            
            logger.section("Starting Alfresco (Recovery)")
            logger.info("PostgreSQL will start in recovery mode")
            logger.info("Monitor recovery progress with: tail -f {}/alf_data/postgresql/postgresql.log".format(config.alf_base_dir))
            
            if not restore.start_alfresco():
                logger.error("Failed to start Alfresco")
                logger.info("Recovery may still be in progress. Check PostgreSQL logs.")
            
            logger.section("PITR Restore Complete")
            logger.info("Point-in-time recovery initiated successfully!")
            logger.info(f"Backup log: {log_file}")
        
        elif restore_mode == 3:
            logger.section("PostgreSQL Only Restore")
            logger.error("PostgreSQL-only mode not yet fully implemented")
            sys.exit(1)
        
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
