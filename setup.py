#!/usr/bin/env python3
"""
Interactive setup script for Alfresco Large Content Store Backup System.
Run this script after cloning the repository to set up all required configurations.

Can be run as regular user (will prompt for sudo when needed) or with sudo.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Tuple

class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header(message: str):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{message}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 80}{Colors.ENDC}\n")

def print_info(message: str):
    print(f"{Colors.OKBLUE}{message}{Colors.ENDC}")

def print_success(message: str):
    print(f"{Colors.OKGREEN}✓ {message}{Colors.ENDC}")

def print_warning(message: str):
    print(f"{Colors.WARNING}⚠ {message}{Colors.ENDC}")

def print_error(message: str):
    print(f"{Colors.FAIL}✗ {message}{Colors.ENDC}")

def get_real_user() -> Tuple[str, int, int]:
    """
    Get the real user (not root) even if script is run with sudo.
    Returns: (username, uid, gid)
    """
    if os.geteuid() == 0:  # Running as root
        # Get the user who ran sudo
        sudo_user = os.environ.get('SUDO_USER')
        if sudo_user:
            # Get UID and GID of the real user
            import pwd
            try:
                pw_record = pwd.getpwnam(sudo_user)
                return (sudo_user, pw_record.pw_uid, pw_record.pw_gid)
            except KeyError:
                pass
    
    # Not running as root, or couldn't find SUDO_USER
    return (os.environ.get('USER', 'unknown'), os.getuid(), os.getgid())

def is_running_as_root() -> bool:
    """Check if script is running as root/sudo."""
    return os.geteuid() == 0

def ask_yes_no(question: str, default: bool = True) -> bool:
    """Ask a yes/no question and return the answer."""
    default_str = "Y/n" if default else "y/N"
    while True:
        response = input(f"{Colors.OKCYAN}{question} [{default_str}]: {Colors.ENDC}").strip().lower()
        if not response:
            return default
        if response in ['y', 'yes']:
            return True
        if response in ['n', 'no']:
            return False
        print_warning("Please answer 'y' or 'n'")

def run_command(cmd: list, capture_output: bool = False, check: bool = True) -> Optional[subprocess.CompletedProcess]:
    """Run a shell command. Returns CompletedProcess or None."""
    try:
        result = subprocess.run(cmd, capture_output=capture_output, text=True, check=False)
        
        if result.returncode != 0 and check:
            print_error(f"Command failed with exit code {result.returncode}: {' '.join(cmd)}")
            if capture_output and result.stderr:
                print_error(f"Error: {result.stderr.strip()}")
            return None
        
        return result if (capture_output or not check) else None
        
    except FileNotFoundError:
        print_error(f"Command not found: {cmd[0]}")
        return None
    except Exception as e:
        print_error(f"Error running command: {e}")
        return None

def check_prerequisites():
    """Check if required tools are installed."""
    print_header("Step 1: Checking Prerequisites")
    
    print_info("Checking for required tools...")
    
    required_tools = {
        'python3': 'Python 3',
        'pg_basebackup': 'PostgreSQL client tools',
        'rsync': 'rsync',
        'sudo': 'sudo'
    }
    
    missing_tools = []
    for cmd, name in required_tools.items():
        result = run_command(['which', cmd], capture_output=True, check=False)
        if result and result.returncode == 0:
            print_success(f"{name} is installed")
        else:
            print_error(f"{name} is NOT installed")
            missing_tools.append(name)
    
    if missing_tools:
        print_error(f"\nMissing required tools: {', '.join(missing_tools)}")
        print_info("\nInstall them with:")
        print("  sudo apt-get update")
        print("  sudo apt-get install -y python3 python3-pip python3-venv postgresql-client rsync")
        sys.exit(1)
    
    print_success("\nAll prerequisites are installed!")
    return ask_yes_no("\nContinue with setup?")

def create_env_file():
    """Create or verify .env file."""
    print_header("Step 2: Environment Configuration")
    
    env_file = Path('.env')
    env_example = Path('env.example')
    
    if env_file.exists():
        print_info(f".env file already exists at: {env_file.absolute()}")
        if not ask_yes_no("Do you want to reconfigure it?", default=False):
            return True
    
    print_info("\nThe .env file contains all configuration for the backup system.")
    print_info("You need to provide:")
    print_info("  - PostgreSQL connection details (host, port, user, password)")
    print_info("  - Backup directory path")
    print_info("  - Alfresco base directory path")
    print_info("  - Retention policy (days)")
    print_info("  - Email alert settings (optional)")
    
    if not ask_yes_no("\nCreate/update .env file now?"):
        print_warning("Skipping .env creation. You must create it manually before running backups.")
        return False
    
    # Collect configuration
    print_info("\n--- Database Configuration ---")
    pg_host = input(f"{Colors.OKCYAN}PostgreSQL host [localhost]: {Colors.ENDC}").strip() or 'localhost'
    pg_port = input(f"{Colors.OKCYAN}PostgreSQL port [5432]: {Colors.ENDC}").strip() or '5432'
    pg_user = input(f"{Colors.OKCYAN}PostgreSQL user [alfresco]: {Colors.ENDC}").strip() or 'alfresco'
    pg_password = input(f"{Colors.OKCYAN}PostgreSQL password: {Colors.ENDC}").strip()
    
    print_info("\n--- Paths Configuration ---")
    backup_dir = input(f"{Colors.OKCYAN}Backup directory [/mnt/backups/alfresco]: {Colors.ENDC}").strip() or '/mnt/backups/alfresco'
    alf_base_dir = input(f"{Colors.OKCYAN}Alfresco base directory [/opt/alfresco]: {Colors.ENDC}").strip() or '/opt/alfresco'
    
    print_info("\n--- Retention Policy ---")
    retention_days = input(f"{Colors.OKCYAN}Retention period in days [30]: {Colors.ENDC}").strip() or '30'
    
    print_info("\n--- Email Alerts (optional - only sent on failures) ---")
    configure_email = ask_yes_no("Configure email alerts?", default=False)
    
    if configure_email:
        smtp_host = input(f"{Colors.OKCYAN}SMTP host [smtp.gmail.com]: {Colors.ENDC}").strip() or 'smtp.gmail.com'
        smtp_port = input(f"{Colors.OKCYAN}SMTP port [587]: {Colors.ENDC}").strip() or '587'
        smtp_user = input(f"{Colors.OKCYAN}SMTP username: {Colors.ENDC}").strip()
        smtp_password = input(f"{Colors.OKCYAN}SMTP password: {Colors.ENDC}").strip()
        alert_email = input(f"{Colors.OKCYAN}Alert recipient email: {Colors.ENDC}").strip()
        alert_from = input(f"{Colors.OKCYAN}Alert from email [{smtp_user}]: {Colors.ENDC}").strip() or smtp_user
    else:
        smtp_host = smtp_port = smtp_user = smtp_password = alert_email = alert_from = ''
    
    # Write .env file
    env_content = f"""# Database Configuration
PGHOST={pg_host}
PGPORT={pg_port}
PGUSER={pg_user}
PGPASSWORD={pg_password}

# Paths
BACKUP_DIR={backup_dir}
ALF_BASE_DIR={alf_base_dir}

# Retention Policy
RETENTION_DAYS={retention_days}

# Email Alerts (only sent on failures)
SMTP_HOST={smtp_host}
SMTP_PORT={smtp_port}
SMTP_USER={smtp_user}
SMTP_PASSWORD={smtp_password}
ALERT_EMAIL={alert_email}
ALERT_FROM={alert_from}
"""
    
    with open(env_file, 'w') as f:
        f.write(env_content)
    
    # Set ownership if running as root
    if is_running_as_root():
        real_user, real_uid, real_gid = get_real_user()
        os.chown(env_file, real_uid, real_gid)
    
    os.chmod(env_file, 0o600)  # Secure the file
    
    print_success(f"\n.env file created at: {env_file.absolute()}")
    print_success("File permissions set to 600 (read/write for owner only)")
    
    return True

def load_env_config() -> dict:
    """Load configuration from .env file."""
    config = {}
    env_file = Path('.env')
    
    if not env_file.exists():
        return config
    
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                config[key.strip()] = value.strip()
    
    return config

def create_directories():
    """Create backup directories."""
    print_header("Step 3: Create Backup Directories")
    
    config = load_env_config()
    backup_dir = config.get('BACKUP_DIR')
    
    if not backup_dir:
        print_error("BACKUP_DIR not found in .env file")
        return False
    
    real_user, real_uid, real_gid = get_real_user()
    running_as_root = is_running_as_root()
    
    print_info(f"This will create the following directory structure:")
    print_info(f"  {backup_dir}/")
    print_info(f"  ├── postgres/")
    print_info(f"  ├── contentstore/")
    print_info(f"  └── pg_wal/")
    print_info(f"\nAll directories will be owned by: {real_user}")
    
    if running_as_root:
        print_info("(Running with sudo privileges)")
    
    if not ask_yes_no("\nCreate backup directories?"):
        print_warning("Skipping directory creation")
        return False
    
    try:
        # Create main backup directory
        if running_as_root:
            # We have root privileges, create directly
            Path(backup_dir).mkdir(parents=True, exist_ok=True)
            print_success(f"Created: {backup_dir}")
            
            # Set ownership to real user
            os.chown(backup_dir, real_uid, real_gid)
            print_success(f"Set ownership to {real_user}")
        else:
            # Try to create without sudo first
            try:
                Path(backup_dir).mkdir(parents=True, exist_ok=True)
                print_success(f"Created: {backup_dir}")
            except PermissionError:
                # Need sudo to create parent directories
                print_warning(f"Permission denied creating {backup_dir}")
                print_info(f"\nNeed sudo access to create directory in {Path(backup_dir).parent}")
                print_info("Please re-run this script with sudo:")
                print_info(f"  sudo python3 setup.py")
                return False
        
        # Create subdirectories
        for subdir in ['postgres', 'contentstore', 'pg_wal']:
            path = Path(backup_dir) / subdir
            path.mkdir(exist_ok=True)
            if running_as_root:
                os.chown(path, real_uid, real_gid)
            print_success(f"Created: {path}")
        
        return True
        
    except Exception as e:
        print_error(f"Error creating directories: {e}")
        return False

def get_postgres_user() -> Optional[str]:
    """Detect or ask for the PostgreSQL system user."""
    # Try common PostgreSQL user names
    common_users = ['postgres', 'postgresql', 'pgsql']
    
    for user in common_users:
        result = run_command(['id', user], capture_output=True, check=False)
        if result and result.returncode == 0:
            return user
    
    return None

def configure_wal_archive():
    """Help configure WAL archive directory for PostgreSQL."""
    print_header("Step 4: Configure WAL Archive Directory for PostgreSQL")
    
    config = load_env_config()
    backup_dir = config.get('BACKUP_DIR')
    
    if not backup_dir:
        print_error("BACKUP_DIR not found in .env file")
        return False
    
    wal_dir = Path(backup_dir) / 'pg_wal'
    
    if not wal_dir.exists():
        print_error(f"WAL directory does not exist: {wal_dir}")
        print_error("Directory creation in Step 3 may have failed")
        return False
    
    print_info("PostgreSQL needs write access to the WAL archive directory.")
    print_info(f"WAL directory: {wal_dir}")
    
    # Detect PostgreSQL user
    pg_user = get_postgres_user()
    real_user, real_uid, real_gid = get_real_user()
    running_as_root = is_running_as_root()
    
    if not pg_user:
        print_warning("\nCould not detect PostgreSQL system user (tried: postgres, postgresql, pgsql)")
        print_info("This might mean:")
        print_info("  - PostgreSQL is not installed on this system")
        print_info("  - PostgreSQL uses a different username")
        print_info("  - Alfresco uses an embedded PostgreSQL")
        
        custom_user = input(f"{Colors.OKCYAN}Enter PostgreSQL system user (or press Enter to skip): {Colors.ENDC}").strip()
        
        if custom_user:
            # Verify the user exists
            result = run_command(['id', custom_user], capture_output=True, check=False)
            if result and result.returncode == 0:
                pg_user = custom_user
            else:
                print_error(f"User '{custom_user}' does not exist on this system")
                print_warning("Skipping WAL directory configuration")
                print_info("\nYou will need to configure this manually:")
                print_info(f"  sudo chown <postgres_user>:{real_user} {wal_dir}")
                print_info(f"  sudo chmod 770 {wal_dir}")
                return False
        else:
            print_warning("Skipping WAL directory configuration")
            print_info("\nYou will need to configure this manually:")
            print_info(f"  sudo chown <postgres_user>:{real_user} {wal_dir}")
            print_info(f"  sudo chmod 770 {wal_dir}")
            return False
    
    print_info(f"\nDetected PostgreSQL user: {pg_user}")
    print_info(f"\nThis will:")
    print_info(f"  1. Set ownership to {pg_user}:{real_user}")
    print_info(f"  2. Set permissions to 770 (rwxrwx---)")
    print_info(f"  3. Allow both PostgreSQL and {real_user} to access the directory")
    
    if running_as_root:
        print_info("(Running with sudo privileges)")
    
    if not ask_yes_no("\nConfigure WAL directory permissions?"):
        print_warning("Skipping WAL directory configuration")
        print_warning("You will need to configure this manually for backups to work")
        return False
    
    try:
        # Get postgres user UID
        import pwd
        try:
            pg_pw_record = pwd.getpwnam(pg_user)
            pg_uid = pg_pw_record.pw_uid
        except KeyError:
            print_error(f"Could not find UID for user: {pg_user}")
            return False
        
        # Change ownership
        if running_as_root:
            # We already have root, use os.chown directly
            print_info(f"\nSetting ownership to {pg_user}:{real_user}")
            os.chown(wal_dir, pg_uid, real_gid)
            print_success(f"Set ownership to {pg_user}:{real_user}")
        else:
            # Need sudo
            print_info(f"\nRunning: sudo chown {pg_user}:{real_user} {wal_dir}")
            result = run_command(['sudo', 'chown', f'{pg_user}:{real_user}', str(wal_dir)], capture_output=True, check=False)
            
            if result and result.returncode == 0:
                print_success(f"Set ownership to {pg_user}:{real_user}")
            else:
                print_error(f"Failed to set ownership")
                if result and result.stderr:
                    print_error(f"Error: {result.stderr.strip()}")
                return False
        
        # Change permissions
        if running_as_root:
            print_info("Setting permissions to 770")
            os.chmod(wal_dir, 0o770)
            print_success("Set permissions to 770")
        else:
            print_info(f"Running: sudo chmod 770 {wal_dir}")
            result = run_command(['sudo', 'chmod', '770', str(wal_dir)], capture_output=True, check=False)
            
            if result and result.returncode == 0:
                print_success("Set permissions to 770")
            else:
                print_error("Failed to set permissions")
                if result and result.stderr:
                    print_error(f"Error: {result.stderr.strip()}")
                return False
        
        return True
        
    except Exception as e:
        print_error(f"Error configuring WAL directory: {e}")
        return False

def find_postgresql_conf(alf_base_dir: str) -> Optional[Path]:
    """Find postgresql.conf file for Alfresco embedded PostgreSQL."""
    # Try common locations for Alfresco embedded PostgreSQL
    possible_paths = [
        Path(alf_base_dir) / 'postgresql' / 'postgresql.conf',
        Path(alf_base_dir) / 'alf_data' / 'postgresql' / 'postgresql.conf',
    ]
    
    for path in possible_paths:
        if path.exists():
            return path
    
    return None

def find_pg_hba_conf(alf_base_dir: str) -> Optional[Path]:
    """Find pg_hba.conf file for Alfresco embedded PostgreSQL."""
    # Try common locations for Alfresco embedded PostgreSQL
    possible_paths = [
        Path(alf_base_dir) / 'postgresql' / 'pg_hba.conf',
        Path(alf_base_dir) / 'alf_data' / 'postgresql' / 'pg_hba.conf',
    ]
    
    for path in possible_paths:
        if path.exists():
            return path
    
    return None

def backup_file(file_path: Path) -> bool:
    """Create a backup of a file with .backup extension."""
    backup_path = Path(str(file_path) + '.backup')
    
    if backup_path.exists():
        print_info(f"Backup already exists: {backup_path}")
        return True
    
    try:
        shutil.copy2(file_path, backup_path)
        print_success(f"Created backup: {backup_path}")
        return True
    except Exception as e:
        print_error(f"Failed to create backup: {e}")
        return False

def update_postgresql_conf_setting(file_path: Path, setting: str, value: str, wal_dir: str = None) -> bool:
    """Update or add a setting in postgresql.conf."""
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
        
        # Replace %p and %f placeholders in archive_command if needed
        if setting == 'archive_command' and wal_dir:
            value = value.replace('%WAL_DIR%', wal_dir)
        
        setting_found = False
        new_lines = []
        
        for line in lines:
            stripped = line.strip()
            
            # Check if this line contains our setting
            if stripped.startswith(setting + ' ') or stripped.startswith(setting + '=') or stripped.startswith('#' + setting):
                if not setting_found:
                    # Replace with our value
                    new_lines.append(f"{setting} = {value}\n")
                    setting_found = True
                    print_info(f"  Updated: {setting} = {value}")
                # Skip duplicate lines
            else:
                new_lines.append(line)
        
        # If setting wasn't found, add it at the end
        if not setting_found:
            new_lines.append(f"\n# Added by backup setup script\n")
            new_lines.append(f"{setting} = {value}\n")
            print_info(f"  Added: {setting} = {value}")
        
        # Write back
        with open(file_path, 'w') as f:
            f.writelines(new_lines)
        
        return True
        
    except Exception as e:
        print_error(f"Failed to update {setting}: {e}")
        return False

def update_pg_hba_conf(file_path: Path, pg_user: str) -> bool:
    """Add replication entry to pg_hba.conf if not already present."""
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
        
        # Check if replication entry already exists
        replication_entry = f"local   replication     {pg_user}"
        entry_exists = any(replication_entry in line for line in lines)
        
        if entry_exists:
            print_info(f"  Replication entry for {pg_user} already exists")
            return True
        
        # Add the entry
        new_lines = lines.copy()
        new_lines.append(f"\n# Added by backup setup script for pg_basebackup\n")
        new_lines.append(f"local   replication     {pg_user}                                md5\n")
        
        with open(file_path, 'w') as f:
            f.writelines(new_lines)
        
        print_info(f"  Added: local replication entry for {pg_user}")
        return True
        
    except Exception as e:
        print_error(f"Failed to update pg_hba.conf: {e}")
        return False

def detect_postgresql_version(pg_conf: Path) -> tuple:
    """Detect PostgreSQL version from config file path or by checking version."""
    # Try to read version from config file comments or nearby files
    version_file = pg_conf.parent / 'PG_VERSION'
    
    if version_file.exists():
        try:
            with open(version_file, 'r') as f:
                version_str = f.read().strip()
                # Convert "9.4" to (9, 4)
                parts = version_str.split('.')
                major = int(parts[0])
                minor = int(parts[1]) if len(parts) > 1 else 0
                return (major, minor)
        except:
            pass
    
    # Default to PostgreSQL 9.4 (Alfresco 5.2 default)
    print_warning("Could not detect PostgreSQL version, assuming 9.4 (Alfresco 5.2)")
    return (9, 4)

def get_wal_level_value(pg_version: tuple) -> str:
    """Get appropriate wal_level value based on PostgreSQL version."""
    major, minor = pg_version
    
    # PostgreSQL 9.6+ uses "replica"
    # PostgreSQL 9.4-9.5 uses "hot_standby"
    if major > 9 or (major == 9 and minor >= 6):
        return 'replica'
    else:
        return 'hot_standby'

def configure_postgresql():
    """Automatically configure PostgreSQL for WAL archiving."""
    print_header("Step 5: Configure PostgreSQL for WAL Archiving")
    
    config = load_env_config()
    backup_dir = config.get('BACKUP_DIR')
    alf_base_dir = config.get('ALF_BASE_DIR')
    pg_user = config.get('PGUSER', 'alfresco')
    
    if not backup_dir or not alf_base_dir:
        print_error("BACKUP_DIR or ALF_BASE_DIR not found in .env file")
        return False
    
    wal_dir = str(Path(backup_dir) / 'pg_wal')
    
    print_info("Alfresco 5.2 comes with embedded PostgreSQL 9.4.")
    print_info("This step will configure it for WAL archiving to enable backups.")
    print_info(f"\nLooking for PostgreSQL configuration in: {alf_base_dir}")
    
    # Find postgresql.conf
    pg_conf = find_postgresql_conf(alf_base_dir)
    if not pg_conf:
        print_error(f"Could not find postgresql.conf in {alf_base_dir}")
        print_info("\nTried these locations:")
        print_info(f"  {alf_base_dir}/postgresql/postgresql.conf")
        print_info(f"  {alf_base_dir}/alf_data/postgresql/postgresql.conf")
        return False
    
    print_success(f"Found postgresql.conf: {pg_conf}")
    
    # Detect PostgreSQL version
    pg_version = detect_postgresql_version(pg_conf)
    print_info(f"Detected PostgreSQL version: {pg_version[0]}.{pg_version[1]}")
    
    # Get appropriate wal_level for this version
    wal_level_value = get_wal_level_value(pg_version)
    
    # Find pg_hba.conf
    pg_hba = find_pg_hba_conf(alf_base_dir)
    if not pg_hba:
        print_error(f"Could not find pg_hba.conf in {alf_base_dir}")
        return False
    
    print_success(f"Found pg_hba.conf: {pg_hba}")
    
    print_info("\nThe following settings will be configured:")
    print_info(f"  1. wal_level = {wal_level_value}")
    if pg_version[0] == 9 and pg_version[1] == 4:
        print_info("     (Using 'hot_standby' for PostgreSQL 9.4)")
    print_info("  2. archive_mode = on")
    print_info(f"  3. archive_command = 'test ! -f {wal_dir}/%f && cp %p {wal_dir}/%f'")
    print_info("  4. max_wal_senders = 3")
    
    # For PostgreSQL 9.4, use wal_keep_segments instead of wal_keep_size
    if pg_version[0] == 9 and pg_version[1] < 13:
        print_info("  5. wal_keep_segments = 64 (for PostgreSQL 9.4)")
    else:
        print_info("  5. wal_keep_size = 1GB")
    
    print_info("  6. Add replication entry to pg_hba.conf")
    print_info("\n⚠ Original files will be backed up before modification")
    print_info("⚠ PostgreSQL will need to be restarted after these changes")
    
    if not ask_yes_no("\nProceed with PostgreSQL configuration?"):
        print_warning("Skipping PostgreSQL configuration")
        print_warning("Backups will not work until PostgreSQL is configured manually")
        return False
    
    running_as_root = is_running_as_root()
    
    # Backup postgresql.conf
    print_info("\nBacking up configuration files...")
    if not backup_file(pg_conf):
        return False
    if not backup_file(pg_hba):
        return False
    
    # Update postgresql.conf settings
    print_info("\nUpdating postgresql.conf...")
    
    settings = [
        ('wal_level', wal_level_value),
        ('archive_mode', 'on'),
        ('archive_command', f"'test ! -f {wal_dir}/%f && cp %p {wal_dir}/%f'"),
        ('max_wal_senders', '3'),
    ]
    
    # Add version-specific setting
    if pg_version[0] == 9 and pg_version[1] < 13:
        settings.append(('wal_keep_segments', '64'))
    else:
        settings.append(('wal_keep_size', '1GB'))
    
    for setting, value in settings:
        if not update_postgresql_conf_setting(pg_conf, setting, value, wal_dir):
            print_error(f"Failed to update {setting}")
            return False
    
    print_success("postgresql.conf updated successfully")
    
    # Update pg_hba.conf
    print_info("\nUpdating pg_hba.conf...")
    if not update_pg_hba_conf(pg_hba, pg_user):
        print_error("Failed to update pg_hba.conf")
        return False
    
    print_success("pg_hba.conf updated successfully")
    
    # Instructions for restarting
    print_info("\n" + "="*80)
    print_info("IMPORTANT: RESTART POSTGRESQL")
    print_info("="*80)
    
    print_warning("\n⚠ PostgreSQL must be restarted for changes to take effect")
    print_info("\nTo restart Alfresco's embedded PostgreSQL:")
    print_info("  1. Stop Alfresco:")
    print_info(f"     {alf_base_dir}/alfresco.sh stop")
    print_info("  2. Start Alfresco:")
    print_info(f"     {alf_base_dir}/alfresco.sh start")
    print_info("\nOR if you have systemd service:")
    print_info("  sudo systemctl restart alfresco")
    
    if ask_yes_no("\nWould you like to see the grant replication privilege command?"):
        print_info("\nAfter restarting, grant replication privilege:")
        print_info(f"  psql -h localhost -U {pg_user} -d postgres -c \"ALTER USER {pg_user} REPLICATION;\"")
    
    return True

def create_virtual_environment():
    """Create Python virtual environment and install dependencies."""
    print_header("Step 6: Create Virtual Environment")
    
    venv_path = Path('venv')
    real_user, real_uid, real_gid = get_real_user()
    running_as_root = is_running_as_root()
    
    print_info("Creating a Python virtual environment isolates dependencies.")
    print_info(f"Virtual environment will be created at: {venv_path.absolute()}")
    print_info(f"Virtual environment will be owned by: {real_user}")
    
    if venv_path.exists():
        print_warning(f"Virtual environment already exists at: {venv_path}")
        if not ask_yes_no("Recreate it?", default=False):
            print_info("Skipping virtual environment creation")
            return True
        print_info("Removing existing virtual environment...")
        shutil.rmtree(venv_path)
    
    if not ask_yes_no("\nCreate virtual environment and install dependencies?"):
        print_warning("Skipping virtual environment creation")
        return False
    
    try:
        # Create venv
        print_info("\nCreating virtual environment...")
        
        if running_as_root:
            # Run as the real user using sudo -u
            print_info(f"Running as user {real_user} (not root)")
            result = run_command(['sudo', '-u', real_user, sys.executable, '-m', 'venv', 'venv'], check=True)
        else:
            result = run_command([sys.executable, '-m', 'venv', 'venv'], check=True)
        
        if result is None:
            print_success("Virtual environment created")
        else:
            return False
        
        # Determine pip path
        pip_path = venv_path / 'bin' / 'pip'
        
        # Install dependencies
        print_info("\nInstalling dependencies from requirements.txt...")
        
        if running_as_root:
            # Run pip as the real user
            result = run_command(['sudo', '-u', real_user, str(pip_path), 'install', '-r', 'requirements.txt'], check=True)
        else:
            result = run_command([str(pip_path), 'install', '-r', 'requirements.txt'], check=True)
        
        if result is None:
            print_success("Dependencies installed")
        else:
            return False
        
        print_success(f"\nVirtual environment ready at: {venv_path.absolute()}")
        print_info("\nTo activate the virtual environment:")
        print(f"  source {venv_path}/bin/activate")
        
        return True
        
    except Exception as e:
        print_error(f"Error setting up virtual environment: {e}")
        return False

def verify_installation():
    """Verify the installation."""
    print_header("Step 7: Verify Installation")
    
    print_info("Checking if all components are properly set up...")
    
    checks = []
    
    # Check .env
    if Path('.env').exists():
        print_success(".env file exists")
        checks.append(True)
    else:
        print_error(".env file missing")
        checks.append(False)
    
    # Check venv
    venv_python = Path('venv/bin/python')
    if venv_python.exists():
        print_success("Virtual environment exists")
        checks.append(True)
    else:
        print_error("Virtual environment missing")
        checks.append(False)
    
    # Check backup directories
    config = load_env_config()
    backup_dir = config.get('BACKUP_DIR')
    if backup_dir and Path(backup_dir).exists():
        print_success(f"Backup directory exists: {backup_dir}")
        checks.append(True)
    else:
        print_error(f"Backup directory missing: {backup_dir}")
        checks.append(False)
    
    # Check WAL directory
    if backup_dir:
        wal_dir = Path(backup_dir) / 'pg_wal'
        if wal_dir.exists():
            print_success(f"WAL directory exists: {wal_dir}")
            checks.append(True)
        else:
            print_error(f"WAL directory missing: {wal_dir}")
            checks.append(False)
    
    if all(checks):
        print_success("\n✓ All checks passed!")
        print_info("\nNext steps:")
        print_info("  1. Configure PostgreSQL (see instructions above)")
        print_info("  2. Test the backup:")
        print_info("     source venv/bin/activate")
        print_info("     python backup.py")
        print_info("  3. Set up cron job for automated backups (see README.md)")
        return True
    else:
        print_error("\n✗ Some checks failed. Please review the errors above.")
        return False

def main():
    """Main setup flow."""
    print_header("Alfresco Large Content Store Backup - Setup Wizard")
    
    real_user, real_uid, real_gid = get_real_user()
    running_as_root = is_running_as_root()
    
    if running_as_root:
        print_info(f"Running with sudo privileges (real user: {real_user})")
        print_info("All files and directories will be owned by the real user.")
    else:
        print_info(f"Running as user: {real_user}")
        print_info("You may be prompted for sudo password when creating directories.")
    
    print_info("\nThis wizard will guide you through setting up the backup system.")
    print_info("You will be asked for permission before each step.\n")
    
    if not ask_yes_no("Start setup?"):
        print_info("Setup canceled.")
        sys.exit(0)
    
    # Step 1: Check prerequisites
    if not check_prerequisites():
        print_info("Setup canceled.")
        sys.exit(0)
    
    # Step 2: Create .env file
    if not create_env_file():
        print_warning("Setup cannot continue without .env file")
        sys.exit(1)
    
    # Step 3: Create directories
    create_directories()
    
    # Step 4: Configure WAL directory
    configure_wal_archive()
    
    # Step 5: Configure PostgreSQL automatically
    configure_postgresql()
    
    # Step 6: Create virtual environment
    create_virtual_environment()
    
    # Step 7: Verify
    verify_installation()
    
    print_header("Setup Complete!")
    print_info("Review the instructions above for PostgreSQL configuration.")
    print_info("See README.md for detailed documentation.")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print_info("\n\nSetup interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print_error(f"\nUnexpected error: {e}")
        sys.exit(1)

