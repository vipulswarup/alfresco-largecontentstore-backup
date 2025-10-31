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
    pg_user = input(f"{Colors.OKCYAN}PostgreSQL backup user [alfresco]: {Colors.ENDC}").strip() or 'alfresco'
    pg_password = input(f"{Colors.OKCYAN}PostgreSQL backup user password: {Colors.ENDC}").strip()
    pg_database = input(f"{Colors.OKCYAN}PostgreSQL database [postgres]: {Colors.ENDC}").strip() or 'postgres'
    default_superuser = pg_user if pg_user else 'postgres'
    pg_superuser = input(
        f"{Colors.OKCYAN}PostgreSQL superuser (for granting privileges) [{default_superuser}]: {Colors.ENDC}"
    ).strip() or default_superuser
    
    # Auto-detect PostgreSQL system user
    pg_system_user = get_postgres_user()
    if pg_system_user:
        print_info(f"Auto-detected PostgreSQL system user: {pg_system_user}")
    else:
        pg_system_user = input(f"{Colors.OKCYAN}PostgreSQL system user [postgres]: {Colors.ENDC}").strip() or 'postgres'
    
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
PGDATABASE={pg_database}
PGSUPERUSER={pg_superuser}

# PostgreSQL System User (for embedded PostgreSQL)
PG_SYSTEM_USER={pg_system_user}

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
    # For Alfresco embedded PostgreSQL, try to detect the actual user
    real_user, real_uid, real_gid = get_real_user()
    
    # Check if this is an Alfresco setup by looking for common patterns
    try:
        # Check if we're in an Alfresco directory structure
        current_dir = Path.cwd()
        if 'alfresco' in str(current_dir).lower():
            print_info(f"Detected Alfresco environment, using user: {real_user}")
            return real_user
    except:
        pass
    
    # Try common PostgreSQL users
    common_users = ['postgres', 'postgresql', 'pgsql', real_user]
    
    for user in common_users:
        try:
            result = run_command(['id', user], capture_output=True, check=False)
            if result and result.returncode == 0:
                print_info(f"Found PostgreSQL user: {user}")
                return user
        except:
            continue
    
    # If we get here, use the real user as fallback for embedded PostgreSQL
    print_info(f"Using detected user for embedded PostgreSQL: {real_user}")
    return real_user

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
    
    # Get PostgreSQL user from .env file or detect it
    pg_user = config.get('PG_SYSTEM_USER')
    real_user, real_uid, real_gid = get_real_user()
    running_as_root = is_running_as_root()
    
    if not pg_user:
        # Auto-detect if not in .env file
        pg_user = get_postgres_user()
        if pg_user:
            print_info(f"Auto-detected PostgreSQL system user: {pg_user}")
        else:
            pg_user = real_user
            print_info(f"Using current user as PostgreSQL system user: {pg_user}")
    else:
        print_info(f"Using PostgreSQL system user from .env: {pg_user}")
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
    """Add replication entries to pg_hba.conf if not already present."""
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
        
        # Check for each specific entry type
        has_local = False
        has_ipv4 = False
        has_ipv6 = False
        
        for line in lines:
            if line.strip().startswith('#'):
                continue
            if f"local   replication     {pg_user}" in line:
                has_local = True
            if f"host    replication     {pg_user}        127.0.0.1/32" in line:
                has_ipv4 = True
            if f"host    replication     {pg_user}        ::1/128" in line:
                has_ipv6 = True
        
        # Check if all entries exist
        if has_local and has_ipv4 and has_ipv6:
            print_info(f"  All replication entries for {pg_user} already exist")
            return True
        
        # Add missing entries
        new_lines = lines.copy()
        entries_added = []
        
        if not has_local and not has_ipv4 and not has_ipv6:
            # Add header comment only if adding all entries
            new_lines.append(f"\n# Added by backup setup script for pg_basebackup\n")
        
        if not has_local:
            new_lines.append(f"# Allow replication connections via Unix socket\n")
            new_lines.append(f"local   replication     {pg_user}                                md5\n")
            entries_added.append("local")
        
        if not has_ipv4:
            new_lines.append(f"# Allow replication connections via TCP/IP from localhost (IPv4)\n")
            new_lines.append(f"host    replication     {pg_user}        127.0.0.1/32            md5\n")
            entries_added.append("IPv4")
        
        if not has_ipv6:
            new_lines.append(f"# Allow replication connections via TCP/IP from localhost (IPv6)\n")
            new_lines.append(f"host    replication     {pg_user}        ::1/128                 md5\n")
            entries_added.append("IPv6")
        
        with open(file_path, 'w') as f:
            f.writelines(new_lines)
        
        print_info(f"  Added replication entries for {pg_user}: {', '.join(entries_added)}")
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
    pg_password = config.get('PGPASSWORD', '')
    pg_superuser = config.get('PGSUPERUSER', 'postgres')
    pg_database = config.get('PGDATABASE', 'postgres')
    
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
    
    # Instructions for restarting and granting privileges
    print_info("\n" + "="*80)
    print_info("IMPORTANT: RESTART ALFRESCO AND GRANT REPLICATION PRIVILEGES")
    print_info("="*80)
    
    print_warning("\n⚠ Alfresco must be restarted for PostgreSQL changes to take effect")
    print_warning("⚠ The replication privilege must be granted after restart")
    
    print_info(f"\nThe script will automatically:")
    print_info(f"  1. Restart Alfresco to apply PostgreSQL configuration changes")
    print_info(f"  2. Grant replication privilege to '{pg_user}' using superuser '{pg_superuser}'")
    print_info(f"  3. Verify the privilege was granted successfully")
    
    if ask_yes_no("\nProceed with automatic restart and privilege grant?", default=True):
        restart_success = restart_alfresco_and_grant_privileges(alf_base_dir, pg_user, pg_password, pg_superuser, pg_database)
        if not restart_success:
            print_warning("\n⚠ Automatic setup encountered issues")
            print_info("\nIf needed, run these manual steps:")
            print_info(f"  1. Restart Alfresco: bash {alf_base_dir}/alfresco.sh stop && bash {alf_base_dir}/alfresco.sh start")
            print_info(f"  2. Grant privilege (using superuser): psql -h localhost -U {pg_superuser} -d postgres -c \"ALTER USER {pg_user} REPLICATION;\"")
            print_info(f"  3. Or use embedded PostgreSQL: {alf_base_dir}/postgresql/bin/psql -U {pg_superuser} -d postgres -c \"ALTER USER {pg_user} REPLICATION;\"")
        # Return True anyway - PostgreSQL is configured, just needs manual restart
        return True
    else:
        print_info("\nManual steps required:")
        print_info("  1. Stop Alfresco:")
        print_info(f"     bash {alf_base_dir}/alfresco.sh stop")
        print_info("  2. Start Alfresco:")
        print_info(f"     bash {alf_base_dir}/alfresco.sh start")
        print_info("  3. Grant replication privilege (using superuser):")
        print_info(f"     psql -h localhost -U {pg_superuser} -d postgres -c \"ALTER USER {pg_user} REPLICATION;\"")
        print_info(f"  4. Or use embedded PostgreSQL:")
        print_info(f"     {alf_base_dir}/postgresql/bin/psql -U {pg_superuser} -d postgres -c \"ALTER USER {pg_user} REPLICATION;\"")
        return True



def find_alfresco_java_process(real_user: str, alf_base_dir: str) -> Optional[int]:
    """Find the Alfresco Tomcat Java process PID."""
    try:
        # First try: Look for Java process with Alfresco directory in command line
        cmd = ['pgrep', '-u', real_user, '-f', f'java.*{alf_base_dir}']
        result = run_command(cmd, capture_output=True, check=False)
        
        if result and result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            if pids:
                return int(pids[0])  # Return first matching PID
        
        # Second try: Look for any Java process owned by the user (broader search)
        cmd = ['pgrep', '-u', real_user, 'java']
        result = run_command(cmd, capture_output=True, check=False)
        
        if result and result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            if pids:
                # Return the first Java process (most likely to be Alfresco)
                return int(pids[0])
        
        return None
    except:
        return None

def kill_alfresco_process(pid: int, real_user: str) -> bool:
    """Send SIGTERM to Alfresco process."""
    try:
        print_warning(f"Sending SIGTERM to process {pid}...")
        result = run_command(['sudo', '-u', real_user, 'kill', '-15', str(pid)], capture_output=True, check=False)
        return result and result.returncode == 0
    except:
        return False

def cleanup_trust(pg_hba_conf: Path, trust_comment: str, trust_line: str) -> bool:
    """Remove temporary trust lines from pg_hba.conf."""
    try:
        with open(pg_hba_conf, 'r') as f:
            lines = f.readlines()
        if trust_comment in lines:
            lines.remove(trust_comment)
        if trust_line in lines:
            lines.remove(trust_line)
        with open(pg_hba_conf, 'w') as f:
            f.writelines(lines)
        print_success("Restored original authentication")
        return True
    except Exception as e:
        print_error(f"Failed to restore pg_hba.conf: {e}")
        return False


def restart_alfresco_and_grant_privileges(alf_base_dir: str, pg_user: str, pg_password: str, pg_superuser: str = 'postgres', pg_database: str = 'postgres') -> bool:
    """Restart Alfresco and grant replication privileges."""
    print_info("\n" + "="*60)
    print_info("RESTARTING ALFRESCO")
    print_info("="*60)
    
    alfresco_script = Path(alf_base_dir) / 'alfresco.sh'
    
    if not alfresco_script.exists():
        print_error(f"Alfresco control script not found: {alfresco_script}")
        return False
    
    print_info(f"Alfresco control script: {alfresco_script}")
    
    
    print_warning("\nNote: Alfresco restart can be unpredictable:")
    print_warning("  - May take a long time or appear to hang")
    print_warning("  - If not stopped within 60 seconds, will be forcefully terminated")
    print_warning("  - Script may have shell compatibility issues")
    
    if not ask_yes_no("\nAttempt automatic Alfresco restart?", default=True):
        print_info("\nManual restart required:")
        print_info(f"  bash {alf_base_dir}/alfresco.sh stop")
        print_info(f"  bash {alf_base_dir}/alfresco.sh start")
        print_info("\nAfter restarting, grant replication privilege:")
        print_info(f"  psql -h localhost -U {pg_user} -d postgres -c \"ALTER USER {pg_user} REPLICATION;\"")
        print_warning("\nSetup will continue, but you must restart Alfresco manually")
        return False
    
    import time
    
    # Run as the correct user (evadm) only
    real_user, real_uid, real_gid = get_real_user()
    
    stop_commands = [
        ['sudo', '-u', real_user, 'bash', '-c', f'cd {alf_base_dir} && bash {alfresco_script} stop'],
    ]
    
    start_commands = [
        ['sudo', '-u', real_user, 'bash', '-c', f'cd {alf_base_dir} && bash {alfresco_script} start'],
    ]
    
    # Stop Alfresco with timeout
    print_info("\nStopping Alfresco...")
    stop_cmd = stop_commands[0]
    print_info(f"Running: sudo -u {real_user} bash -c 'cd {alf_base_dir} && bash {alfresco_script} stop'")
    print_info("Stop command timeout: 30 seconds")
    
    # Use timeout to prevent hanging
    timeout_cmd = ['timeout', '30'] + stop_cmd
    result = run_command(timeout_cmd, capture_output=True, check=False)
    
    if result and result.returncode == 0:
        print_success("Alfresco stop command completed")
    elif result and result.returncode == 124:
        print_warning("Alfresco stop command timed out after 30 seconds - process may be stuck")
    else:
        print_warning("Alfresco stop command may have failed")
        if result:
            if result.stdout:
                print_info(f"Output: {result.stdout.strip()}")
            if result.stderr:
                print_warning(f"Error: {result.stderr.strip()}")
    
    # Wait for processes to stop with timeout
    print_info("Waiting for Alfresco processes to stop (timeout: 60 seconds)...")
    timeout = 60
    elapsed = 0
    check_interval = 2
    
    # Start with a shorter timeout since stop command already had 30 seconds
    remaining_timeout = 30
    
    while elapsed < remaining_timeout:
        pid = find_alfresco_java_process(real_user, alf_base_dir)
        if not pid:
            print_success(f"Alfresco stopped successfully (after {elapsed} seconds)")
            break
        
        time.sleep(check_interval)
        elapsed += check_interval
        
        if elapsed % 10 == 0:
            print_info(f"  Still waiting... ({elapsed}/{remaining_timeout} seconds)")
    else:
        # Timeout reached, force kill
        print_warning(f"Alfresco did not stop gracefully after {remaining_timeout} seconds")
        pid = find_alfresco_java_process(real_user, alf_base_dir)
        if pid:
            print_warning(f"Found Alfresco Java process (PID: {pid})")
            if kill_alfresco_process(pid, real_user):
                print_success(f"Sent SIGTERM to process {pid}")
                time.sleep(5)  # Give it a few seconds to terminate
                
                # Check if it's still running
                if find_alfresco_java_process(real_user, alf_base_dir):
                    print_warning("Process still running after SIGTERM, may need manual intervention")
                else:
                    print_success("Process terminated successfully")
            else:
                print_error("Failed to send SIGTERM to process")
        else:
            print_success("Alfresco process not found (may have stopped)")
    
    # Additional wait to ensure cleanup
    time.sleep(3)
    
    # Start Alfresco
    print_info("\nStarting Alfresco...")
    start_cmd = start_commands[0]
    print_info(f"Running: sudo -u {real_user} bash -c 'cd {alf_base_dir} && bash {alfresco_script} start'")
    
    result = run_command(start_cmd, capture_output=True, check=False)
    
    if result and result.returncode == 0:
        print_success("Alfresco started successfully")
    else:
        print_error("Alfresco start failed")
        if result:
            if result.stdout:
                print_info(f"Output: {result.stdout.strip()}")
            if result.stderr:
                print_error(f"Error: {result.stderr.strip()}")
        print_info("\nPlease restart Alfresco manually:")
        print_info(f"  sudo -u {real_user} bash -c 'cd {alf_base_dir} && bash {alfresco_script} stop'")
        print_info(f"  sudo -u {real_user} bash -c 'cd {alf_base_dir} && bash {alfresco_script} start'")
        print_warning("\nContinuing setup without replication privilege grant...")
        return False
    
    print_success("Alfresco restarted successfully")
    
    # Wait for PostgreSQL to be ready
    print_info("Waiting for PostgreSQL to be ready...")
    time.sleep(10)
    
    # Grant replication privileges
    print_info("\n" + "="*60)
    print_info("GRANTING REPLICATION PRIVILEGES")
    print_info("="*60)
    
    print_info(f"Granting replication privilege to user: {pg_user}")
    print_info(f"Note: This requires superuser access via role '{pg_superuser or pg_user}'")
    
    # Define paths and temporary trust configuration
    pg_data_dir = Path(alf_base_dir) / "alf_data" / "postgresql"
    pg_hba_conf = pg_data_dir / "pg_hba.conf"
    pg_ctl_script = Path(alf_base_dir) / "postgresql" / "scripts" / "ctl.sh"
    pg_ctl_bin = Path(alf_base_dir) / "postgresql" / "bin" / "pg_ctl"
    psql_bin = Path(alf_base_dir) / "postgresql" / "bin" / "psql"
    effective_superuser = pg_superuser or pg_user
    trust_comment = "# Added by backup setup script for temporary superuser trust\n"
    trust_line = f"local   all             {effective_superuser}                                trust\n"
    trust_added = False

    if pg_hba_conf.exists():
        # Backup authentication file before modifications
        backup_created = backup_file(pg_hba_conf)
        if backup_created:
            print_success(f"Backed up PostgreSQL authentication config: {pg_hba_conf}.backup")
        else:
            print_info("Using existing pg_hba.conf backup")
        with open(pg_hba_conf, 'r') as f:
            lines = f.readlines()
        if trust_line not in lines:
            print_info(f"Temporarily allowing trust authentication for PostgreSQL role '{effective_superuser}'")
            lines.insert(0, trust_line)
            lines.insert(0, trust_comment)
            with open(pg_hba_conf, 'w') as f:
                f.writelines(lines)
            trust_added = True

    # Pre-check: Skip if replication already granted (after ensuring trust access)
    if psql_bin.exists():
        superuser_check = ['sudo', '-u', real_user, str(psql_bin), '-U', effective_superuser, '-d', pg_database, '-c', 'SELECT 1;']
        result = run_command(superuser_check, capture_output=True, check=False)
        if not (result and result.returncode == 0):
            if pg_user and pg_superuser != pg_user:
                print_warning(f"Could not connect as PostgreSQL superuser '{pg_superuser}'. Falling back to '{pg_user}'.")
            effective_superuser = pg_user
            trust_line = f"local   all             {effective_superuser}                                trust\n"
            if pg_hba_conf.exists():
                with open(pg_hba_conf, 'r') as f:
                    lines = f.readlines()
                if trust_line not in lines:
                    print_info(f"Temporarily allowing trust authentication for PostgreSQL role '{effective_superuser}'")
                    lines.insert(0, trust_line)
                    lines.insert(0, trust_comment)
                    with open(pg_hba_conf, 'w') as f:
                        f.writelines(lines)
                    trust_added = True

    # Reload PostgreSQL configuration to apply trust changes
    if trust_added:
        reload_cmd = None
        if pg_ctl_bin.exists():
            reload_cmd = ['sudo', '-u', real_user, str(pg_ctl_bin), '-D', str(pg_data_dir), 'reload']
        elif pg_ctl_script.exists():
            reload_cmd = ['sudo', '-u', real_user, str(pg_ctl_script), 'reload']
        if reload_cmd:
            result = run_command(reload_cmd, capture_output=True, check=False)
            if result and result.returncode == 0:
                print_success("PostgreSQL configuration reloaded to apply trust authentication")
            else:
                print_warning("PostgreSQL reload failed; continuing with existing session")

    if psql_bin.exists():
        check_cmd = ['sudo', '-u', real_user, str(psql_bin), '-U', effective_superuser, '-d', pg_database, '-c', f"SELECT rolreplication FROM pg_roles WHERE rolname = '{pg_user}';"]
        result = run_command(check_cmd, capture_output=True, check=False)
        if result and result.returncode == 0 and 't' in result.stdout:
            print_success(f"User {pg_user} already has replication privileges")
            return True
    print_info("Using embedded PostgreSQL approach:")
    print_info(f"  PostgreSQL data directory: {pg_data_dir}")
    print_info(f"  Authentication config: {pg_hba_conf}")
    
    if not pg_hba_conf.exists():
        print_error(f"PostgreSQL config file not found: {pg_hba_conf}")
        return False
    
    if not psql_bin.exists():
        print_error(f"PostgreSQL client not found: {psql_bin}")
        return False
    
    # Step 1: Back up pg_hba.conf
    print_info("\n1. Backing up pg_hba.conf...")
    if not pg_hba_conf.exists():
        print_error(f"PostgreSQL config file not found: {pg_hba_conf}")
        return False
    else:
        print_info("Backup already created earlier in this step")
    
    # Step 2: Add trust authentication
    print_info("2. Adding trust authentication...")
    if trust_added:
        print_info(f"Trust entry for role '{effective_superuser}' already configured")
    else:
        print_info("Trust authentication already present; no changes needed")
    
    # Step 3: Restart PostgreSQL
    print_info("3. Restarting PostgreSQL...")
    restart_cmd = None
    
    if pg_ctl_script.exists():
        restart_cmd = ['sudo', '-u', real_user, str(pg_ctl_script), 'restart']
        print_info(f"Using: {pg_ctl_script}")
    elif pg_ctl_bin.exists():
        restart_cmd = ['sudo', '-u', real_user, str(pg_ctl_bin), '-D', str(pg_data_dir), 'restart']
        print_info(f"Using: {pg_ctl_bin}")
    else:
        print_error("No PostgreSQL control script found")
        return False
    
    result = run_command(restart_cmd, capture_output=True, check=False)
    if result and result.returncode == 0:
        print_success("PostgreSQL restarted")
    else:
        print_warning("PostgreSQL restart may have failed")
        if result and result.stderr:
            print_warning(f"Error: {result.stderr.strip()}")
    
    # Step 4: Check if PostgreSQL role exists, create if needed
    print_info("4. Checking if PostgreSQL role exists...")
    check_role_cmd = ['sudo', '-u', real_user, str(psql_bin), '-U', effective_superuser, '-d', pg_database, '-t', '-c', f"SELECT 1 FROM pg_roles WHERE rolname = '{pg_user}';"]
    
    result = run_command(check_role_cmd, capture_output=True, check=False)
    role_exists = result and result.returncode == 0 and '1' in result.stdout
    
    if not role_exists:
        print_warning(f"PostgreSQL role '{pg_user}' does not exist")
        print_info(f"Creating PostgreSQL role '{pg_user}'...")
        
        # Create the role with LOGIN and password
        create_role_cmd = ['sudo', '-u', real_user, str(psql_bin), '-U', effective_superuser, '-d', pg_database, '-c', f"CREATE ROLE {pg_user} LOGIN PASSWORD '{pg_password}';"]
        
        result = run_command(create_role_cmd, capture_output=True, check=False)
        if result and result.returncode == 0:
            print_success(f"PostgreSQL role '{pg_user}' created successfully")
        else:
            print_error(f"Failed to create PostgreSQL role '{pg_user}'")
            if result and result.stderr:
                print_error(f"Error: {result.stderr.strip()}")
            return False
    else:
        print_success(f"PostgreSQL role '{pg_user}' already exists")
    
    # Step 5: Grant replication privileges
    print_info("5. Granting replication privileges...")
    
    # Connect as superuser with trust authentication
    psql_cmd = ['sudo', '-u', real_user, str(psql_bin), '-U', effective_superuser, '-d', pg_database, '-c', f'ALTER USER {pg_user} WITH REPLICATION;']
    
    result = run_command(psql_cmd, capture_output=True, check=False)
    if result and result.returncode == 0:
        print_success("Replication privilege granted")
    else:
        print_error("Failed to grant replication privilege")
        if result and result.stderr:
            print_error(f"Error: {result.stderr.strip()}")
        return False
    
    # Step 6: Verify privileges
    print_info("6. Verifying privileges...")
    verify_cmd = ['sudo', '-u', real_user, str(psql_bin), '-U', effective_superuser, '-d', pg_database, '-c', f"SELECT rolreplication FROM pg_roles WHERE rolname = '{pg_user}';"]
    
    result = run_command(verify_cmd, capture_output=True, check=False)
    if result and result.returncode == 0 and 't' in result.stdout:
        print_success("Replication privilege verified")
    else:
        print_error("Replication privilege verification failed")
        cleanup_trust(pg_hba_conf, trust_comment, trust_line)
        return False
    
    # Step 7: Restore original authentication
    print_info("7. Restoring original authentication...")
    if not cleanup_trust(pg_hba_conf, trust_comment, trust_line):
        return False
    
    # Step 8: Restart PostgreSQL again
    print_info("8. Final PostgreSQL restart...")
    result = run_command(restart_cmd, capture_output=True, check=False)
    if result and result.returncode == 0:
        print_success("PostgreSQL restarted with secure authentication")
    else:
        print_warning("PostgreSQL restart may have failed")
        if result and result.stderr:
            print_warning(f"Error: {result.stderr.strip()}")
    
    # Step 9: Final verification
    print_info("9. Final verification...")
    final_verify = ['sudo', '-u', real_user, str(psql_bin), '-U', effective_superuser, '-d', pg_database, '-c', f"SELECT rolreplication FROM pg_roles WHERE rolname = '{pg_user}';"]
    
    result = run_command(final_verify, capture_output=True, check=False)
    if result and result.returncode == 0 and 't' in result.stdout:
        print_success("✓ Replication privileges confirmed")
        return True
    else:
        print_error("Replication privileges could not be confirmed; please run the ALTER USER command manually.")
        return False

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

def configure_cron_job():
    """Configure cron job for automated backups."""
    print_header("Step 7: Configure Cron Job")
    
    real_user, real_uid, real_gid = get_real_user()
    current_dir = Path.cwd().absolute()
    venv_python = current_dir / 'venv' / 'bin' / 'python'
    backup_script = current_dir / 'backup.py'
    log_dir = Path('/var/log/alfresco-backup')
    
    print_info("Setting up automated daily backups via cron.")
    print_info(f"Cron job will be added for user: {real_user}")
    
    running_as_root = is_running_as_root()
    
    # Check if cron job already exists
    # Use -u flag when running as root to target the real user's crontab
    crontab_cmd = ['crontab', '-u', real_user, '-l'] if running_as_root else ['crontab', '-l']
    result = run_command(crontab_cmd, capture_output=True, check=False)
    existing_crontab = result.stdout if result and result.returncode == 0 else ""
    
    if 'backup.py' in existing_crontab and str(current_dir) in existing_crontab:
        print_success("Cron job already configured")
        print_info("\nExisting cron entry found:")
        for line in existing_crontab.split('\n'):
            if 'backup.py' in line:
                print_info(f"  {line}")
        
        if not ask_yes_no("\nReconfigure cron job?", default=False):
            return True
    
    # Ask for schedule
    print_info("\nDefault schedule: Daily at 2:00 AM")
    if ask_yes_no("Use default schedule?", default=True):
        cron_time = "0 2 * * *"
        schedule_desc = "2:00 AM daily"
    else:
        print_info("\nEnter cron schedule (format: minute hour day month weekday)")
        print_info("Examples:")
        print_info("  0 2 * * *    - 2:00 AM every day")
        print_info("  0 3 * * 0    - 3:00 AM every Sunday")
        print_info("  0 */6 * * *  - Every 6 hours")
        cron_time = input(f"{Colors.OKCYAN}Cron schedule: {Colors.ENDC}").strip() or "0 2 * * *"
        schedule_desc = cron_time
    
    # Create log directory if it doesn't exist
    print_info(f"\nLog directory will be: {log_dir}")
    print_info(f"Log files will be: {log_dir}/cron-YYYY-MM-DD.log")
    
    if not log_dir.exists():
        try:
            # Try to create directory without sudo first
            log_dir.mkdir(parents=True, exist_ok=True)
            os.chown(log_dir, real_uid, real_gid)
            os.chmod(log_dir, 0o755)
            print_success(f"Created log directory: {log_dir}")
        except PermissionError:
            print_warning(f"Cannot create {log_dir} - need sudo")
            if ask_yes_no("Create log directory with sudo?"):
                result = run_command(['sudo', 'mkdir', '-p', str(log_dir)], check=False)
                if result is None or result.returncode == 0:
                    run_command(['sudo', 'chown', f'{real_user}:{real_user}', str(log_dir)], check=False)
                    run_command(['sudo', 'chmod', '755', str(log_dir)], check=False)
                    print_success(f"Created log directory: {log_dir}")
                else:
                    print_error(f"Failed to create log directory")
                    print_warning("Cron job will fail without a writable log directory")
                    return False
            else:
                print_warning("Cron job will fail without a writable log directory")
                return False
    else:
        print_success(f"Log directory already exists: {log_dir}")
        # Verify permissions
        try:
            test_file = log_dir / '.test'
            test_file.touch()
            test_file.unlink()
            print_success(f"Log directory is writable by {real_user}")
        except PermissionError:
            print_error(f"Log directory exists but is not writable by {real_user}")
            if ask_yes_no("Fix permissions with sudo?"):
                run_command(['sudo', 'chown', f'{real_user}:{real_user}', str(log_dir)], check=False)
                run_command(['sudo', 'chmod', '755', str(log_dir)], check=False)
                print_success("Fixed log directory permissions")
            else:
                print_warning("Cron job may fail due to permission issues")
                return False
    
    # Build cron command with date-stamped log file
    cron_command = f"cd {current_dir} && {venv_python} {backup_script} >> {log_dir}/cron-$(date +\\%Y-\\%m-\\%d).log 2>&1"
    cron_entry = f"{cron_time} {cron_command}"
    
    print_info("\nCron entry to be added:")
    print_info(f"  {cron_entry}")
    print_info(f"\nThis will run backups: {schedule_desc}")
    print_info(f"Logs will be written to: {log_dir}/cron-YYYY-MM-DD.log")
    
    if not ask_yes_no("\nAdd this cron job?"):
        print_warning("Skipping cron job configuration")
        print_info("\nTo add manually later:")
        print_info("  crontab -e")
        print_info(f"  # Add: {cron_entry}")
        return False
    
    # Add cron job
    try:
        # Build new crontab content
        new_crontab = existing_crontab
        
        # Remove any existing backup.py entries for this directory to avoid duplicates
        if existing_crontab:
            lines = []
            for line in existing_crontab.split('\n'):
                if not ('backup.py' in line and str(current_dir) in line):
                    lines.append(line)
            new_crontab = '\n'.join(lines).strip()
        
        # Add new entry
        if new_crontab:
            new_crontab += '\n'
        new_crontab += f"\n# Alfresco backup - added by setup script\n"
        new_crontab += f"{cron_entry}\n"
        
        # Write new crontab
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write(new_crontab)
            temp_file = f.name
        
        try:
            # Install new crontab (use -u flag when running as root)
            install_cmd = ['crontab', '-u', real_user, temp_file] if running_as_root else ['crontab', temp_file]
            result = run_command(install_cmd, check=False)
            if result and result.returncode == 0:
                print_success("Cron job added successfully")
                
                # Verify (use -u flag when running as root)
                verify_cmd = ['crontab', '-u', real_user, '-l'] if running_as_root else ['crontab', '-l']
                result = run_command(verify_cmd, capture_output=True, check=False)
                if result and 'backup.py' in result.stdout:
                    print_success(f"Verified: Cron job is active for user {real_user}")
                return True
            else:
                print_error("Failed to add cron job")
                return False
        finally:
            os.unlink(temp_file)
            
    except Exception as e:
        print_error(f"Error configuring cron job: {e}")
        print_info("\nTo add manually:")
        print_info("  crontab -e")
        print_info(f"  # Add: {cron_entry}")
        return False

def verify_installation():
    """Verify the installation."""
    print_header("Step 8: Verify Installation")
    
    print_info("Performing comprehensive verification of all components...")
    
    checks = []
    warnings = []
    
    # Check .env
    print_info("\n[1/8] Checking .env configuration file...")
    env_file = Path('.env')
    if env_file.exists():
        print_success(".env file exists")
        config = load_env_config()
        
        # Verify required settings
        required_settings = ['BACKUP_DIR', 'ALF_BASE_DIR', 'PGUSER', 'PGHOST', 'PGPORT']
        missing = [s for s in required_settings if not config.get(s)]
        if missing:
            print_error(f"Missing required settings in .env: {', '.join(missing)}")
            checks.append(False)
        else:
            print_success("All required settings present in .env")
            checks.append(True)
    else:
        print_error(".env file missing")
        checks.append(False)
        config = {}
    
    # Check backup directories
    print_info("\n[2/8] Checking backup directories...")
    backup_dir = config.get('BACKUP_DIR')
    if backup_dir and Path(backup_dir).exists():
        print_success(f"Backup directory exists: {backup_dir}")
        
        # Check subdirectories
        for subdir in ['postgres', 'contentstore', 'pg_wal']:
            path = Path(backup_dir) / subdir
            if path.exists():
                print_success(f"  {subdir}/ exists")
            else:
                print_error(f"  {subdir}/ missing")
                checks.append(False)
        checks.append(True)
    else:
        print_error(f"Backup directory missing: {backup_dir}")
        checks.append(False)
    
    # Check PostgreSQL configuration
    print_info("\n[3/8] Checking PostgreSQL WAL configuration...")
    alf_base_dir = config.get('ALF_BASE_DIR')
    if alf_base_dir:
        try:
            from alfresco_backup.utils.wal_config_check import check_wal_configuration
        except ImportError:
            import importlib
            check_wal_configuration = importlib.import_module('wal_config_check').check_wal_configuration
        
        # Create a simple config object
        class Config:
            def __init__(self, alf_base_dir):
                self.alf_base_dir = Path(alf_base_dir)
        
        result = check_wal_configuration(Config(alf_base_dir))
        
        if result['success']:
            print_success("PostgreSQL WAL configuration is valid")
            settings = result.get('settings', {})
            print_info(f"  wal_level: {settings.get('wal_level', 'not set')}")
            print_info(f"  archive_mode: {settings.get('archive_mode', 'not set')}")
            print_info(f"  archive_command: {settings.get('archive_command', 'not set')[:50]}...")
            checks.append(True)
        else:
            print_error("PostgreSQL WAL configuration issues:")
            if result.get('error'):
                print_error(f"  {result['error']}")
            checks.append(False)
        
        for warning in result.get('warnings', []):
            warnings.append(f"PostgreSQL: {warning}")
    else:
        print_warning("Cannot verify PostgreSQL config - ALF_BASE_DIR not set")
        checks.append(False)
    
    # Check replication privilege
    print_info("\n[4/8] Checking PostgreSQL replication privilege...")
    pg_user = config.get('PGUSER', 'alfresco')
    pg_superuser = config.get('PGSUPERUSER', 'postgres')
    pg_host = config.get('PGHOST', 'localhost')
    pg_port = config.get('PGPORT', '5432')
    alf_base_dir = config.get('ALF_BASE_DIR', '/opt/alfresco')
    
    verify_cmd = ['psql', '-h', pg_host, '-p', pg_port, '-U', pg_user, '-d', 'postgres', '-t', '-c', 
                  f"SELECT rolreplication FROM pg_roles WHERE rolname = '{pg_user}';"]
    
    result = run_command(verify_cmd, capture_output=True, check=False)
    if result and result.returncode == 0:
        output = result.stdout.strip()
        if 't' in output:
            print_success(f"Replication privilege granted to {pg_user}")
            checks.append(True)
        else:
            print_error(f"Replication privilege NOT granted to {pg_user}")
            print_info(f"  Run this command using the PostgreSQL superuser:")
            print_info(f"  psql -h localhost -U {pg_superuser} -d postgres -c \"ALTER USER {pg_user} REPLICATION;\"")
            print_info(f"  Or use embedded PostgreSQL:")
            print_info(f"  {alf_base_dir}/postgresql/bin/psql -U {pg_superuser} -d postgres -c \"ALTER USER {pg_user} REPLICATION;\"")
            checks.append(False)
    else:
        print_warning("Cannot verify replication privilege (PostgreSQL may not be running)")
        warnings.append("Replication privilege could not be verified")
        checks.append(True)  # Don't fail on this
    
    # Check virtual environment
    print_info("\n[5/8] Checking Python virtual environment...")
    venv_python = Path('venv/bin/python')
    if venv_python.exists():
        print_success("Virtual environment exists")
        
        # Check if dependencies are installed
        pip_path = Path('venv/bin/pip')
        result = run_command([str(pip_path), 'list'], capture_output=True, check=False)
        if result and 'python-dotenv' in result.stdout:
            print_success("  Dependencies installed")
        else:
            print_warning("  Dependencies may not be installed")
        checks.append(True)
    else:
        print_error("Virtual environment missing")
        checks.append(False)
    
    # Check contentstore path
    print_info("\n[6/8] Checking Alfresco contentstore path...")
    if alf_base_dir:
        contentstore_path = Path(alf_base_dir) / 'alf_data' / 'contentstore'
        if contentstore_path.exists():
            print_success(f"Contentstore found: {contentstore_path}")
            checks.append(True)
        else:
            print_error(f"Contentstore not found: {contentstore_path}")
            print_info("  Verify ALF_BASE_DIR is correct in .env")
            checks.append(False)
    else:
        print_warning("Cannot verify contentstore - ALF_BASE_DIR not set")
        checks.append(False)
    
    # Check backup script permissions
    print_info("\n[7/8] Checking backup script...")
    backup_script = Path('backup.py')
    if backup_script.exists():
        print_success("backup.py exists")
        if os.access(backup_script, os.X_OK):
            print_success("  backup.py is executable")
        else:
            print_info("  backup.py is not executable (run: chmod +x backup.py)")
        checks.append(True)
    else:
        print_error("backup.py missing")
        checks.append(False)
    
    # Check cron job
    print_info("\n[8/8] Checking cron job configuration...")
    real_user, real_uid, real_gid = get_real_user()
    running_as_root = is_running_as_root()
    
    # Use -u flag when running as root to check the real user's crontab
    crontab_cmd = ['crontab', '-u', real_user, '-l'] if running_as_root else ['crontab', '-l']
    result = run_command(crontab_cmd, capture_output=True, check=False)
    
    if result and result.returncode == 0:
        if 'backup.py' in result.stdout:
            print_success(f"Cron job configured for backup.py (user: {real_user})")
            checks.append(True)
        else:
            print_warning(f"No cron job found for backup.py in {real_user}'s crontab")
            print_info("  Add to crontab for automated backups (see README.md)")
            warnings.append("Cron job not configured")
            checks.append(True)  # Not a failure
    else:
        print_info(f"No crontab configured yet for user {real_user}")
        warnings.append("Cron job not configured")
        checks.append(True)  # Not a failure
    
    # Summary
    print_info("\n" + "="*80)
    print_info("VERIFICATION SUMMARY")
    print_info("="*80)
    
    if warnings:
        print_warning("\nWarnings:")
        for warning in warnings:
            print_warning(f"  - {warning}")
    
    if all(checks):
        print_success("\n✓ All critical checks passed!")
        print_info("\nYour backup system is ready to use.")
        print_info("\nNext step - Test the backup:")
        print_info("  source venv/bin/activate")
        print_info("  python backup.py")
        return True
    else:
        print_error("\n✗ Some critical checks failed. Please review the errors above.")
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
    
    # Step 7: Configure cron job
    configure_cron_job()
    
    # Step 8: Verify
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

