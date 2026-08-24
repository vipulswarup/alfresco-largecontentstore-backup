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

from alfresco_backup.restic_installer import install_restic_release

# Allow imports when setup.py is run from the repo root (not installed as a package).
sys.path.insert(0, str(Path(__file__).resolve().parent))


def add_venv_site_packages() -> bool:
    """Make dependencies from ./venv importable while setup.py keeps running."""
    venv_path = Path(__file__).resolve().parent / 'venv'
    lib_dir = venv_path / 'lib'
    if not lib_dir.exists():
        return False

    candidates = []
    exact_python = lib_dir / f'python{sys.version_info.major}.{sys.version_info.minor}'
    if exact_python.exists():
        candidates.append(exact_python / 'site-packages')
        candidates.extend(
            p for p in exact_python.iterdir()
            if p.is_dir() and 'site-packages' in p.name
        )
    candidates.extend(p / 'site-packages' for p in lib_dir.glob('python*') if p.is_dir())

    for site_packages in candidates:
        if site_packages.exists():
            site_path = str(site_packages)
            if site_path not in sys.path:
                sys.path.insert(0, site_path)
            return True
    return False


add_venv_site_packages()

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
    print(f"{Colors.OKGREEN}{message}{Colors.ENDC}")

def print_warning(message: str):
    print(f"{Colors.WARNING}WARNING: {message}{Colors.ENDC}")

def print_error(message: str):
    print(f"{Colors.FAIL}ERROR: {message}{Colors.ENDC}")

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

def run_command(
    cmd: list,
    capture_output: bool = False,
    check: bool = True,
    quiet: bool = False,
) -> Optional[subprocess.CompletedProcess]:
    """Run a shell command with consistent logging."""
    if not quiet:
        print_info(f"Running command: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=capture_output, text=True, check=False)
        if result.returncode != 0:
            if not quiet:
                print_error(f"Command exited with {result.returncode}")
            if capture_output:
                if result.stdout:
                    print_info(f"STDOUT:\n{result.stdout.strip()}")
                if result.stderr:
                    print_error(f"STDERR:\n{result.stderr.strip()}")
            if check:
                return None
        else:
            if capture_output and result.stdout:
                print_info(f"STDOUT:\n{result.stdout.strip()}")
        return result
    except FileNotFoundError:
        print_error(f"Command not found: {cmd[0]}")
        return None
    except Exception as e:
        print_error(f"Error running command: {e}")
        return None

def check_rclone_installed() -> bool:
    """Check if rclone is installed."""
    result = run_command(['which', 'rclone'], capture_output=True, check=False)
    return result is not None and result.returncode == 0


def install_rclone() -> bool:
    """Install rclone using apt."""
    print_info("Installing rclone...")
    
    if not is_running_as_root():
        print_warning("Need sudo privileges to install rclone")
        if not ask_yes_no("Install rclone with sudo?", default=True):
            return False
        
        result = run_command(['sudo', 'apt-get', 'update'], capture_output=True, check=False)
        if result is None or result.returncode != 0:
            print_error("Failed to update apt package list")
            return False
        
        result = run_command(['sudo', 'apt-get', 'install', '-y', 'rclone'], capture_output=True, check=False)
        if result is None or result.returncode != 0:
            print_error("Failed to install rclone")
            if result and result.stderr:
                print_error(f"Error: {result.stderr.strip()}")
            return False
    else:
        result = run_command(['apt-get', 'update'], capture_output=True, check=False)
        if result is None or result.returncode != 0:
            print_error("Failed to update apt package list")
            return False
        
        result = run_command(['apt-get', 'install', '-y', 'rclone'], capture_output=True, check=False)
        if result is None or result.returncode != 0:
            print_error("Failed to install rclone")
            if result and result.stderr:
                print_error(f"Error: {result.stderr.strip()}")
            return False
    
    if check_rclone_installed():
        print_success("rclone installed successfully")
        return True
    else:
        print_error("rclone installation completed but rclone command not found")
        return False


def check_prerequisites(for_restore=False):
    """Check if required tools are installed."""
    if not for_restore:
        print_header("Step 1: Checking Prerequisites")
    
    print_info("Checking for required tools...")
    
    if for_restore:
        # For restore, only need Python and basic tools
        required_tools = {
            'python3': 'Python 3',
        }
    else:
        # For backup setup, need all tools
        required_tools = {
            'python3': 'Python 3',
            'pg_dump': 'PostgreSQL client tools (pg_dump)',
            'sudo': 'sudo',
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
        if not for_restore:
            print_info("\nInstall them with:")
            print("  sudo apt-get update")
            print("  sudo apt-get install -y postgresql-client")
            print("\nRestic is installed by the setup wizard if it is missing.")
        else:
            print_info("\nInstall Python 3 with:")
            print("  sudo apt-get update")
            print("  sudo apt-get install -y python3 python3-pip python3-venv")
        sys.exit(1)
    
    print_success("\nAll prerequisites are installed!")
    if not for_restore:
        return ask_yes_no("\nContinue with setup?")
    return True

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
    print_info("  - Backup destination (local directory or S3 bucket)")
    print_info("  - EisenVault source folder path")
    print_info("  - Retention policy (days)")
    print_info("  - Email alert settings (optional)")
    
    if not ask_yes_no("\nCreate/update .env file now?"):
        print_warning("Skipping .env creation. You must create it manually before running backups.")
        return False
    
    # Collect backup destination first
    print_info("\n--- Backup Destination ---")
    print_info("Choose where to store backups:")
    print_info("  1. Local directory (traditional backup to disk)")
    print_info("  2. S3 bucket (cloud backup, requires rclone)")
    
    backup_destination = input(f"{Colors.OKCYAN}Backup destination (1 or 2) [1]: {Colors.ENDC}").strip() or '1'
    
    backup_dir = None
    s3_bucket = None
    s3_region = None
    aws_access_key_id = None
    aws_secret_access_key = None
    
    if backup_destination == '2':
        # S3 backup
        print_info("\n--- S3 Backup Configuration ---")
        print_info("S3 backup will store backups directly to S3 (requires rclone to be installed)")
        print_info("Note: S3 versioning should be enabled on your bucket for incremental backups")
        
        if not check_rclone_installed():
            print_warning("rclone is not installed")
            if ask_yes_no("Install rclone using apt?", default=True):
                if not install_rclone():
                    print_error("Failed to install rclone. Please install it manually:")
                    print_info("  sudo apt-get update")
                    print_info("  sudo apt-get install -y rclone")
                    print_info("\nOr install from: https://rclone.org/install/")
                    if not ask_yes_no("Continue without rclone? (S3 backups will fail)", default=False):
                        return False
            else:
                print_warning("rclone is required for S3 backups")
                print_info("Install it manually with:")
                print("  sudo apt-get update")
                print("  sudo apt-get install -y rclone")
                print("\nOr install from: https://rclone.org/install/")
                if not ask_yes_no("Continue without rclone? (S3 backups will fail)", default=False):
                    return False
        
        while True:
            s3_bucket = input(f"{Colors.OKCYAN}S3 bucket name: {Colors.ENDC}").strip()
            if s3_bucket:
                break
            print_error("S3 bucket name is required for S3 backup")
        
        s3_region = input(f"{Colors.OKCYAN}S3 region [us-east-1]: {Colors.ENDC}").strip() or 'us-east-1'
        while True:
            aws_access_key_id = input(f"{Colors.OKCYAN}AWS Access Key ID: {Colors.ENDC}").strip()
            if aws_access_key_id:
                break
            print_error("AWS Access Key ID is required")
        while True:
            aws_secret_access_key = input(f"{Colors.OKCYAN}AWS Secret Access Key: {Colors.ENDC}").strip()
            if aws_secret_access_key:
                break
            print_error("AWS Secret Access Key is required")
    else:
        # Local backup
        print_info("\n--- Local Backup Directory ---")
        while True:
            backup_dir = input(f"{Colors.OKCYAN}Backup directory path: {Colors.ENDC}").strip()
            if backup_dir and Path(backup_dir).exists():
                break
            print_error(f"Directory does not exist: {backup_dir}")
            print_info("Please enter a valid backup directory path.")
    
    # Collect EisenVault source folder (needed for auto-detection)
    print_info("\n--- Alfresco Base Directory ---")
    while True:
        alf_base_dir = input(f"{Colors.OKCYAN}EisenVault source folder path: {Colors.ENDC}").strip()
        if alf_base_dir and Path(alf_base_dir).exists():
            break
        print_error(f"Directory does not exist: {alf_base_dir}")
        print_info("Please enter a valid EisenVault source folder path.")
    
    # Try to auto-detect database settings from alfresco-global.properties
    print_info("\n--- Database Configuration ---")
    print_info("Attempting to auto-detect database settings from alfresco-global.properties...")
    db_settings = detect_db_settings_from_alfresco(alf_base_dir)
    
    if db_settings:
        print_success("Auto-detected database settings from alfresco-global.properties")
        print_info(f"  Host: {db_settings.get('host', 'not found')}")
        print_info(f"  Port: {db_settings.get('port', 'not found')}")
        print_info(f"  User: {db_settings.get('user', 'not found')}")
        print_info(f"  Database: {db_settings.get('database', 'not found')}")
        
        use_detected = ask_yes_no("Use these detected settings?", default=True)
        
        if use_detected:
            pg_host = db_settings.get('host', 'localhost')
            pg_port = db_settings.get('port', '5432')
            pg_user = db_settings.get('user', 'alfresco')
            pg_password = db_settings.get('password', '')
            pg_database = db_settings.get('database', 'postgres')
            
            # For backup, we typically use 'postgres' database, but allow override
            if pg_database != 'postgres':
                print_info(f"\nNote: Detected database '{pg_database}', but backups typically use 'postgres' database.")
                override_db = input(f"{Colors.OKCYAN}PostgreSQL database for backup [{pg_database}]: {Colors.ENDC}").strip()
                if override_db:
                    pg_database = override_db
        else:
            # Manual entry with detected values as defaults
            pg_host = input(f"{Colors.OKCYAN}PostgreSQL host [{db_settings.get('host', 'localhost')}]: {Colors.ENDC}").strip() or db_settings.get('host', 'localhost')
            pg_port = input(f"{Colors.OKCYAN}PostgreSQL port [{db_settings.get('port', '5432')}]: {Colors.ENDC}").strip() or db_settings.get('port', '5432')
            pg_user = input(f"{Colors.OKCYAN}PostgreSQL user [{db_settings.get('user', 'alfresco')}]: {Colors.ENDC}").strip() or db_settings.get('user', 'alfresco')
            pg_password = input(f"{Colors.OKCYAN}PostgreSQL password: {Colors.ENDC}").strip()
            if not pg_password:
                pg_password = db_settings.get('password', '')
            pg_database = input(f"{Colors.OKCYAN}PostgreSQL database [{db_settings.get('database', 'postgres')}]: {Colors.ENDC}").strip() or db_settings.get('database', 'postgres')
    else:
        print_warning("Could not auto-detect database settings. Please enter manually.")
        pg_host = input(f"{Colors.OKCYAN}PostgreSQL host [localhost]: {Colors.ENDC}").strip() or 'localhost'
        pg_port = input(f"{Colors.OKCYAN}PostgreSQL port [5432]: {Colors.ENDC}").strip() or '5432'
        pg_user = input(f"{Colors.OKCYAN}PostgreSQL user [alfresco]: {Colors.ENDC}").strip() or 'alfresco'
        pg_password = input(f"{Colors.OKCYAN}PostgreSQL password: {Colors.ENDC}").strip()
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
    
    print_info("\n--- Retention Policy ---")
    retention_days = input(f"{Colors.OKCYAN}Retention period in days [7]: {Colors.ENDC}").strip() or '7'
    
    print_info("\n--- Customer Name (optional) ---")
    print_info("Customer name will be displayed prominently in email alerts")
    customer_name = input(f"{Colors.OKCYAN}Customer name (for email alerts): {Colors.ENDC}").strip()
    
    print_info("\n--- Contentstore Backup Timeout (optional) ---")
    print_info("For large contentstores, you may need to increase this timeout")
    timeout_hours = input(f"{Colors.OKCYAN}Contentstore backup timeout in hours [24]: {Colors.ENDC}").strip() or '24'
    try:
        timeout_hours_int = int(timeout_hours)
        if timeout_hours_int < 1:
            print_warning("Timeout must be at least 1 hour, using 24 hours")
            timeout_hours = '24'
    except ValueError:
        print_warning("Invalid timeout value, using 24 hours")
        timeout_hours = '24'
    
    print_info("\n--- Contentstore Parallel Threads (optional) ---")
    print_info("For large backups (5TB+), use 4-8 threads for 2-4x speedup")
    print_info("Each thread processes one top-level directory (typically year directories)")
    print_info("Set to 1 to disable parallelization (slower but simpler)")
    parallel_threads = input(f"{Colors.OKCYAN}Number of parallel threads [4]: {Colors.ENDC}").strip() or '4'
    try:
        parallel_threads_int = int(parallel_threads)
        if parallel_threads_int < 1:
            print_warning("Parallel threads must be at least 1, using 1")
            parallel_threads = '1'
        elif parallel_threads_int > 16:
            print_warning("Parallel threads > 16 may cause issues, capping at 16")
            parallel_threads = '16'
    except ValueError:
        print_warning("Invalid parallel threads value, using 4")
        parallel_threads = '4'
    
    print_info("\n--- Email Alerts (optional) ---")
    configure_email = ask_yes_no("Configure email alerts?", default=False)
    
    if configure_email:
        print_info("\nEmail alert mode:")
        print_info("  - 'both': Send emails on both successful and failed backups")
        print_info("  - 'failure_only': Send emails only on failed backups (default)")
        print_info("  - 'none': Disable email alerts")
        email_alert_mode_input = input(f"{Colors.OKCYAN}Email alert mode [failure_only]: {Colors.ENDC}").strip().lower()
        if email_alert_mode_input not in ['both', 'failure_only', 'none']:
            if email_alert_mode_input:
                print_warning(f"Invalid mode '{email_alert_mode_input}', using 'failure_only'")
            email_alert_mode = 'failure_only'
        else:
            email_alert_mode = email_alert_mode_input
        
        smtp_host = input(f"{Colors.OKCYAN}SMTP host [smtp.gmail.com]: {Colors.ENDC}").strip() or 'smtp.gmail.com'
        smtp_port = input(f"{Colors.OKCYAN}SMTP port [587]: {Colors.ENDC}").strip() or '587'
        smtp_user = input(f"{Colors.OKCYAN}SMTP username: {Colors.ENDC}").strip()
        smtp_password = input(f"{Colors.OKCYAN}SMTP password: {Colors.ENDC}").strip()
        alert_email = input(f"{Colors.OKCYAN}Alert recipient email: {Colors.ENDC}").strip()
        alert_from = input(f"{Colors.OKCYAN}Alert from email [{smtp_user}]: {Colors.ENDC}").strip() or smtp_user
    else:
        email_alert_mode = 'failure_only'
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
# BACKUP_DIR is only required for local backups (not needed for S3 backups)
# Leave empty if using S3 backup
BACKUP_DIR={backup_dir if backup_dir else ''}
EISENVAULT_SOURCE_DIR={alf_base_dir}
EISENVAULT_RESTORE_DIR={alf_base_dir}
# Optional legacy fallback. Set only if source and restore are the same installation.
#ALF_BASE_DIR={alf_base_dir}

# Retention Policy
RETENTION_DAYS={retention_days}

# Customer Name (optional, displayed prominently in email alerts)
CUSTOMER_NAME={customer_name}

# Contentstore Backup Timeout (optional, in hours, default 24)
CONTENTSTORE_TIMEOUT_HOURS={timeout_hours}

# Contentstore Parallel Threads (optional, default 4, set to 1 to disable parallelization)
# For large backups (5TB+), use 4-8 threads for 2-4x speedup
# Each thread processes one top-level directory (typically year directories like 2020/, 2021/)
CONTENTSTORE_PARALLEL_THREADS={parallel_threads}

# S3 Backup Configuration (optional)
# If S3_BUCKET is set, backups will be stored directly to S3 instead of local storage
# Requires rclone to be installed: https://rclone.org/install/
# Note: Enable S3 versioning on your bucket for incremental backups
S3_BUCKET={s3_bucket}
S3_REGION={s3_region}
AWS_ACCESS_KEY_ID={aws_access_key_id}
AWS_SECRET_ACCESS_KEY={aws_secret_access_key}

# Email Alerts
# EMAIL_ALERT_MODE: "both" (send on success and failure), "failure_only" (send only on failure), or "none" (no emails)
EMAIL_ALERT_MODE={email_alert_mode}
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
    s3_enabled = bool(config.get('S3_BUCKET'))
    
    if s3_enabled:
        print_info("S3 mode enabled - skipping local backup directory creation")
        print_info("  Backups will be stored directly to S3")
        return True
    
    backup_dir = config.get('BACKUP_DIR')
    
    if not backup_dir:
        print_error("BACKUP_DIR not found in .env file")
        return False
    
    real_user, real_uid, real_gid = get_real_user()
    running_as_root = is_running_as_root()
    
    print_info(f"This will create the following directory structure:")
    print_info(f"  {backup_dir}/")
    print_info(f"  ├── postgres/")
    print_info(f"  └── contentstore/")
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
        for subdir in ['postgres', 'contentstore']:
            path = Path(backup_dir) / subdir
            path.mkdir(exist_ok=True)
            if running_as_root:
                os.chown(path, real_uid, real_gid)
            print_success(f"Created: {path}")
        
        return True
        
    except Exception as e:
        print_error(f"Error creating directories: {e}")
        return False

def parse_alfresco_global_properties(alf_base_dir: str) -> Optional[dict]:
    """Parse alfresco-global.properties and extract database connection settings."""
    alf_base_path = Path(alf_base_dir)
    
    # Try common locations for alfresco-global.properties
    possible_paths = [
        alf_base_path / 'tomcat' / 'shared' / 'classes' / 'alfresco-global.properties',
        alf_base_path / 'alf_data' / 'tomcat' / 'shared' / 'classes' / 'alfresco-global.properties',
    ]
    
    props_file = None
    for path in possible_paths:
        if path.exists():
            props_file = path
            break
    
    if not props_file:
        return None
    
    try:
        properties = {}
        
        with open(props_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                
                # Parse key=value pairs
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Remove quotes if present
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    
                    properties[key] = value
        
        # Extract database settings
        db_settings = {}
        
        if 'db.username' in properties:
            db_settings['user'] = properties['db.username']
        
        if 'db.password' in properties:
            db_settings['password'] = properties['db.password']
        
        if 'db.name' in properties:
            db_settings['database'] = properties['db.name']
        
        # Parse db.url to extract host and port
        if 'db.url' in properties:
            db_url = properties['db.url']
            # Handle variable substitution (e.g., ${db.name})
            if '${db.name}' in db_url and 'db.name' in properties:
                db_url = db_url.replace('${db.name}', properties['db.name'])
            
            # Parse jdbc:postgresql://host:port/database
            import re
            match = re.search(r'jdbc:postgresql://([^:]+):?(\d+)?/(.+)', db_url)
            if match:
                db_settings['host'] = match.group(1)
                db_settings['port'] = match.group(2) or '5432'
                # Database name from URL overrides db.name if present
                if not db_settings.get('database'):
                    db_settings['database'] = match.group(3)
        
        return db_settings if db_settings else None
        
    except Exception as e:
        print_warning(f"Could not parse alfresco-global.properties: {e}")
        return None

def detect_db_settings_from_alfresco(alf_base_dir: Optional[str] = None) -> Optional[dict]:
    """Try to detect database settings from alfresco-global.properties."""
    if not alf_base_dir:
        # Try to get from existing .env or ask user
        config = load_env_config()
        alf_base_dir = (
            config.get('EISENVAULT_SOURCE_DIR')
            or config.get('ALF_SOURCE_DIR')
            or config.get('ALF_BASE_DIR')
        )
        
        if not alf_base_dir:
            # Ask for alf_base_dir first
            alf_base_dir = input(f"{Colors.OKCYAN}EisenVault source folder: {Colors.ENDC}").strip()
    
    if not alf_base_dir or not Path(alf_base_dir).exists():
        return None
    
    return parse_alfresco_global_properties(alf_base_dir)

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
    s3_enabled = bool(config.get('S3_BUCKET'))
    
    if s3_enabled:
        print_info("S3 mode enabled - skipping WAL archive configuration")
        print_info("  WAL archiving is not needed for S3 backups")
        return True
    
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
    s3_enabled = bool(config.get('S3_BUCKET'))
    alf_base_dir = (
        config.get('EISENVAULT_SOURCE_DIR')
        or config.get('ALF_SOURCE_DIR')
        or config.get('ALF_BASE_DIR')
    )
    pg_user = config.get('PGUSER', 'alfresco')
    
    if s3_enabled:
        print_info("S3 mode enabled - skipping PostgreSQL WAL archiving configuration")
        print_info("  WAL archiving is not needed for S3 backups")
        return True
    
    backup_dir = config.get('BACKUP_DIR')
    
    if not backup_dir or not alf_base_dir:
        print_error("BACKUP_DIR and EisenVault source folder not found in .env file")
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
    print_info("\nOriginal files will be backed up before modification")
    print_info("PostgreSQL will need to be restarted after these changes")
    
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
    
    print_info("\nPlease restart Alfresco (alfresco.sh stop/start) for PostgreSQL changes to take effect.")
    print_info("Replication privileges will be handled automatically during verification.")

    return True


def _python_venv_apt_package() -> str:
    return f"python{sys.version_info.major}.{sys.version_info.minor}-venv"


def _ensurepip_available() -> bool:
    try:
        result = subprocess.run(
            [sys.executable, '-c', 'import ensurepip'],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except OSError:
        return False


def _remove_incomplete_venv(venv_path: Path) -> None:
    if venv_path.exists():
        shutil.rmtree(venv_path, ignore_errors=True)


def _install_python_venv_package() -> bool:
    pkg = _python_venv_apt_package()
    apt = 'apt-get' if shutil.which('apt-get') else ('apt' if shutil.which('apt') else None)
    if not apt:
        print_error("Could not detect apt")
        print_info(f"Install {pkg} manually, then rerun setup:")
        print_info(f"  sudo apt install {pkg}")
        return False

    if is_running_as_root():
        if not ask_yes_no(f"Install {pkg} now?", default=True):
            print_info(f"Install it manually, then rerun setup: sudo apt install {pkg}")
            return False
        prefix = []
    else:
        print_warning(f"{pkg} is required to create the virtual environment")
        if not ask_yes_no(f"Install {pkg} with sudo now?", default=True):
            print_info(f"Install it manually, then rerun setup: sudo apt install {pkg}")
            return False
        prefix = ['sudo']

    print_info(f"Installing {pkg}...")
    update = run_command(prefix + [apt, 'update'], check=False)
    if not update or update.returncode != 0:
        print_warning("apt update failed; attempting install anyway")
    install = run_command(prefix + [apt, 'install', '-y', pkg], check=False)
    if not install or install.returncode != 0:
        print_error(f"Failed to install {pkg}")
        print_info(f"Install it manually, then rerun setup: sudo apt install {pkg}")
        return False
    if not _ensurepip_available():
        print_error(f"{pkg} is installed but ensurepip is still unavailable")
        return False
    print_success(f"{pkg} installed")
    return True


def _create_venv_dir(real_user: str, running_as_root: bool) -> Optional[subprocess.CompletedProcess]:
    if running_as_root:
        print_info(f"Running as user {real_user} (not root)")
        return run_command(
            ['sudo', '-u', real_user, sys.executable, '-m', 'venv', 'venv'],
            capture_output=True,
            check=False,
        )
    return run_command([sys.executable, '-m', 'venv', 'venv'], capture_output=True, check=False)


def create_virtual_environment():
    """Create Python virtual environment and install dependencies."""
    print_header("Step 4: Create Virtual Environment")
    
    venv_path = Path('venv')
    real_user, real_uid, real_gid = get_real_user()
    running_as_root = is_running_as_root()
    
    print_info("Creating a Python virtual environment isolates dependencies.")
    print_info(f"Virtual environment will be created at: {venv_path.absolute()}")
    print_info(f"Virtual environment will be owned by: {real_user}")
    
    if venv_path.exists():
        pip_ok = (venv_path / 'bin' / 'pip').exists()
        if not pip_ok:
            print_warning("Existing virtual environment is incomplete (missing pip); recreating it.")
            shutil.rmtree(venv_path)
        else:
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
        if not _ensurepip_available():
            print_error("Python cannot create virtual environments because ensurepip is not available.")
            print_info("On Debian/Ubuntu, install the matching venv package:")
            print_info(f"  sudo apt install {_python_venv_apt_package()}")
            if not _install_python_venv_package():
                return False

        print_info("\nCreating virtual environment...")
        result = _create_venv_dir(real_user, running_as_root)
        if result is None or result.returncode != 0:
            _remove_incomplete_venv(venv_path)
            combined = ''
            if result is not None:
                combined = f"{result.stdout or ''}{result.stderr or ''}"
            if 'ensurepip' in combined.lower():
                print_info("ensurepip is missing; the python3-venv package is required.")
                if _install_python_venv_package():
                    print_info("\nRetrying virtual environment creation...")
                    result = _create_venv_dir(real_user, running_as_root)
            if result is None or result.returncode != 0:
                print_error("Failed to create virtual environment")
                _remove_incomplete_venv(venv_path)
                print_info(f"Install the venv package, then rerun setup:")
                print_info(f"  sudo apt install {_python_venv_apt_package()}")
                return False
        
        print_success("Virtual environment created")
        
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
            print_error("Failed to install dependencies")
            return False
        
        print_success("Dependencies installed")
        
        print_success(f"\nVirtual environment ready at: {venv_path.absolute()}")
        print_info("\nTo activate the virtual environment:")
        print(f"  source {venv_path}/bin/activate")
        
        return True
        
    except Exception as e:
        print_error(f"Error setting up virtual environment: {e}")
        return False

def _load_default_maintenance_config() -> dict:
    """Read global.default_maintenance from backup-policies.yml if present."""
    policies_file = Path('backup-policies.yml')
    defaults = {'enabled': True, 'day_of_week': 'sunday', 'time': '03:30'}
    if not policies_file.exists():
        return defaults
    try:
        import yaml
        with open(policies_file, 'r', encoding='utf-8') as f:
            doc = yaml.safe_load(f) or {}
        return (doc.get('global') or {}).get('default_maintenance') or defaults
    except Exception:
        return defaults


def configure_cron_job():
    """Configure cron job for automated backups."""
    print_header("Step 5: Configure Cron Job")
    
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
    cron_path = '/usr/local/bin:/usr/bin:/bin'
    cron_command = (
        f"PATH={cron_path}; export PATH; cd {current_dir} && {venv_python} "
        f"{backup_script} >> {log_dir}/cron-$(date +\\%Y-\\%m-\\%d).log 2>&1"
    )
    cron_entry = f"{cron_time} {cron_command}"

    maintenance_config = _load_default_maintenance_config()
    maintenance_entry = None
    maintenance_desc = None
    if maintenance_config.get('enabled', True):
        from alfresco_backup.v2.schedule import maintenance_cron_expression
        maintenance_cron_time = maintenance_cron_expression(
            str(maintenance_config.get('day_of_week', 'sunday')),
            str(maintenance_config.get('time', '03:30')),
        )
        maintenance_command = (
            f"PATH={cron_path}; export PATH; cd {current_dir} && "
            f"{venv_python} {backup_script} "
            f">> {log_dir}/cron-maintenance-$(date +\\%Y-\\%m-\\%d).log 2>&1"
        )
        maintenance_entry = f"{maintenance_cron_time} {maintenance_command}"
        maintenance_desc = (
            f"{maintenance_config.get('day_of_week', 'sunday').title()} "
            f"at {maintenance_config.get('time', '03:30')} "
            "(scheduled retention pass)"
        )
    
    print_info("\nCron entries to be added:")
    print_info(f"  {cron_entry}")
    print_info(f"\nThis will run backups: {schedule_desc}")
    print_info(f"Logs will be written to: {log_dir}/cron-YYYY-MM-DD.log")
    if maintenance_entry:
        print_info(f"\n  {maintenance_entry}")
        print_info(f"\nThis will run scheduled maintenance: {maintenance_desc}")
        print_info(f"Logs will be written to: {log_dir}/cron-maintenance-YYYY-MM-DD.log")
    else:
        print_info("\nScheduled maintenance cron skipped (default_maintenance.enabled is false).")
    print_info(
        "\nRetention is also enforced after each successful backup "
        "(restic forget/prune per policy retention_days)."
    )
    
    if not ask_yes_no("\nAdd these cron jobs?"):
        print_warning("Skipping cron job configuration")
        print_info("\nTo add manually later:")
        print_info("  crontab -e")
        print_info(f"  # Add: {cron_entry}")
        if maintenance_entry:
            print_info(f"  # Add: {maintenance_entry}")
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
        if maintenance_entry:
            new_crontab += f"{maintenance_entry}\n"
        
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
                print_success("Cron jobs added successfully")
                
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
        if maintenance_entry:
            print_info(f"  # Add: {maintenance_entry}")
        return False

def verify_installation():
    """Verify the installation."""
    print_header("Step 6: Verify Installation")
    
    print_info("Performing comprehensive verification of all components...")
    
    checks = []
    warnings = []
    
    # Check .env
    print_info("\n[1/6] Checking .env configuration file...")
    env_file = Path('.env')
    if env_file.exists():
        print_success(".env file exists")
        config = load_env_config()
        
        required_settings = ['PGUSER', 'PGHOST', 'PGPORT', 'PGPASSWORD']
        missing = [s for s in required_settings if not config.get(s)]
        if not (
            config.get('EISENVAULT_SOURCE_DIR')
            or config.get('ALF_SOURCE_DIR')
            or config.get('ALF_BASE_DIR')
        ):
            missing.append('EISENVAULT_SOURCE_DIR or ALF_BASE_DIR')
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
    
    print_info("\n[2/6] Checking backup-policies.yml (restic destinations)...")
    policies_file = Path('backup-policies.yml')
    if policies_file.exists():
        print_success("backup-policies.yml exists")
        try:
            import yaml
            from alfresco_backup.v2.app_config import AppConfig
            from alfresco_backup.v2.setup_wizard import _ensure_policy_passwords

            with open(policies_file) as f:
                doc = yaml.safe_load(f) or {}
            count = len(doc.get('backup_policies', []))
            print_info(f"  {count} destination(s) configured")
            if count == 0:
                print_error("  No destinations; use setup menu 3, 4, or 5")
                checks.append(False)
            else:
                _ensure_policy_passwords(env_file, policies_file)
                AppConfig(str(env_file), str(policies_file))
                print_success("  Destination configuration is usable")
                checks.append(True)
        except Exception as e:
            print_error(f"  Destination configuration issue: {e}")
            checks.append(False)
    else:
        print_error("backup-policies.yml missing (use setup menu 3 or 4)")
        checks.append(False)

    print_info("\n[2b/6] Checking restic...")
    from alfresco_backup.v2.setup_wizard import check_restic_installed
    if check_restic_installed():
        print_success("restic is installed")
        checks.append(True)
    else:
        print_error("restic not found (setup menu 2)")
        checks.append(False)
    
    # Check virtual environment
    print_info("\n[3/6] Checking Python virtual environment...")
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
    alf_base_dir = (
        config.get('EISENVAULT_SOURCE_DIR')
        or config.get('ALF_SOURCE_DIR')
        or config.get('ALF_BASE_DIR')
    )
    print_info("\n[4/6] Checking EisenVault source contentstore path...")
    if alf_base_dir:
        contentstore_path = Path(alf_base_dir) / 'alf_data' / 'contentstore'
        if contentstore_path.exists():
            print_success(f"Contentstore found: {contentstore_path}")
            checks.append(True)
        else:
            print_error(f"Contentstore not found: {contentstore_path}")
            print_info("  Verify EISENVAULT_SOURCE_DIR or ALF_BASE_DIR is correct in .env")
            checks.append(False)
    else:
        print_warning("Cannot verify contentstore - EISENVAULT_SOURCE_DIR not set")
        checks.append(False)
    
    # Check backup script permissions
    print_info("\n[5/6] Checking backup script...")
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
    print_info("\n[6/6] Checking cron job configuration...")
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
        print_success("\nAll critical checks passed!")
        print_info("\nYour backup system is ready to use.")
        print_info("\nNext step - Test the backup:")
        print_info("  venv/bin/python backup.py")
        print_info("  or setup menu 9. Run backup now")
        return True
    else:
        print_error("\nSome critical checks failed. Please review the errors above.")
        return False

def create_restore_env_file():
    """Create .env file for restore operations with all required configuration."""
    print_header("Restore Configuration")
    
    env_file = Path('.env')
    
    if env_file.exists():
        print_info(f".env file already exists at: {env_file.absolute()}")
        if not ask_yes_no("Do you want to update it with restore configuration?", default=False):
            return True
    
    print_info("\nThe restore script needs the following information:")
    print_info("  - PostgreSQL connection details (host, port, user, password, database)")
    print_info("  - Backup location (local directory or S3 bucket)")
    print_info("  - EisenVault restore folder (target for restore)")
    print_info("  - Alfresco OS user (for file ownership)")
    
    if not ask_yes_no("\nConfigure restore settings now?"):
        print_warning("Skipping .env creation. Restore will fail without configuration.")
        return False
    
    # Collect backup location configuration
    print_info("\n--- Backup Location ---")
    print_info("Choose where backups are stored:")
    print_info("  1. Local directory (traditional backup on disk)")
    print_info("  2. S3 bucket (cloud backup, requires rclone)")
    
    backup_location = input(f"{Colors.OKCYAN}Backup location (1 or 2) [1]: {Colors.ENDC}").strip() or '1'
    
    backup_dir = None
    s3_bucket = None
    s3_region = None
    aws_access_key_id = None
    aws_secret_access_key = None
    
    if backup_location == '2':
        print_info("\n--- S3 Backup Configuration ---")
        print_info("S3 restore will download backups from S3 (requires rclone to be installed)")
        
        if not check_rclone_installed():
            print_warning("rclone is not installed")
            if ask_yes_no("Install rclone using apt?", default=True):
                if not install_rclone():
                    print_error("Failed to install rclone. Please install it manually:")
                    print_info("  sudo apt-get update")
                    print_info("  sudo apt-get install -y rclone")
                    print_info("\nOr install from: https://rclone.org/install/")
                    if not ask_yes_no("Continue without rclone? (S3 restore will fail)", default=False):
                        return False
            else:
                print_warning("rclone is required for S3 restore")
                print_info("Install it manually with:")
                print("  sudo apt-get update")
                print("  sudo apt-get install -y rclone")
                print("\nOr install from: https://rclone.org/install/")
                if not ask_yes_no("Continue without rclone? (S3 restore will fail)", default=False):
                    return False
        
        while True:
            s3_bucket = input(f"{Colors.OKCYAN}S3 bucket name: {Colors.ENDC}").strip()
            if s3_bucket:
                break
            print_error("S3 bucket name is required for S3 restore")
        
        s3_region = input(f"{Colors.OKCYAN}S3 region [us-east-1]: {Colors.ENDC}").strip() or 'us-east-1'
        while True:
            aws_access_key_id = input(f"{Colors.OKCYAN}AWS Access Key ID: {Colors.ENDC}").strip()
            if aws_access_key_id:
                break
            print_error("AWS Access Key ID is required")
        while True:
            aws_secret_access_key = input(f"{Colors.OKCYAN}AWS Secret Access Key: {Colors.ENDC}").strip()
            if aws_secret_access_key:
                break
            print_error("AWS Secret Access Key is required")
    else:
        print_info("\n--- Local Backup Directory ---")
        while True:
            backup_dir = input(f"{Colors.OKCYAN}Backup directory path: {Colors.ENDC}").strip()
            if backup_dir and Path(backup_dir).exists():
                break
            print_error(f"Directory does not exist: {backup_dir}")
            print_info("Please enter a valid backup directory path.")
    
    while True:
        alf_base_dir = input(f"{Colors.OKCYAN}EisenVault restore folder path: {Colors.ENDC}").strip()
        if alf_base_dir and Path(alf_base_dir).exists():
            break
        print_error(f"Directory does not exist: {alf_base_dir}")
        print_info("Please enter a valid EisenVault restore folder path.")
    
    # Try to auto-detect database settings from alfresco-global.properties
    print_info("\n--- PostgreSQL Configuration ---")
    print_info("Attempting to auto-detect database settings from alfresco-global.properties...")
    db_settings = detect_db_settings_from_alfresco(alf_base_dir)
    
    if db_settings:
        print_success("Auto-detected database settings from alfresco-global.properties")
        print_info(f"  Host: {db_settings.get('host', 'not found')}")
        print_info(f"  Port: {db_settings.get('port', 'not found')}")
        print_info(f"  User: {db_settings.get('user', 'not found')}")
        print_info(f"  Database: {db_settings.get('database', 'not found')}")
        
        use_detected = ask_yes_no("Use these detected settings?", default=True)
        
        if use_detected:
            pg_host = db_settings.get('host', 'localhost')
            pg_port = db_settings.get('port', '5432')
            pg_user = db_settings.get('user', 'alfresco')
            pg_password = db_settings.get('password', '')
            pg_database = db_settings.get('database', 'postgres')
        else:
            # Manual entry with detected values as defaults
            pg_host = input(f"{Colors.OKCYAN}PostgreSQL host [{db_settings.get('host', 'localhost')}]: {Colors.ENDC}").strip() or db_settings.get('host', 'localhost')
            pg_port = input(f"{Colors.OKCYAN}PostgreSQL port [{db_settings.get('port', '5432')}]: {Colors.ENDC}").strip() or db_settings.get('port', '5432')
            pg_user = input(f"{Colors.OKCYAN}PostgreSQL user [{db_settings.get('user', 'alfresco')}]: {Colors.ENDC}").strip() or db_settings.get('user', 'alfresco')
            pg_password = input(f"{Colors.OKCYAN}PostgreSQL password: {Colors.ENDC}").strip()
            if not pg_password:
                pg_password = db_settings.get('password', '')
            pg_database = input(f"{Colors.OKCYAN}PostgreSQL database [{db_settings.get('database', 'postgres')}]: {Colors.ENDC}").strip() or db_settings.get('database', 'postgres')
    else:
        print_warning("Could not auto-detect database settings. Please enter manually.")
        pg_host = input(f"{Colors.OKCYAN}PostgreSQL host [localhost]: {Colors.ENDC}").strip() or 'localhost'
        pg_port = input(f"{Colors.OKCYAN}PostgreSQL port [5432]: {Colors.ENDC}").strip() or '5432'
        pg_user = input(f"{Colors.OKCYAN}PostgreSQL user [alfresco]: {Colors.ENDC}").strip() or 'alfresco'
        pg_password = input(f"{Colors.OKCYAN}PostgreSQL password: {Colors.ENDC}").strip()
        pg_database = input(f"{Colors.OKCYAN}PostgreSQL database [postgres]: {Colors.ENDC}").strip() or 'postgres'
    
    if not pg_password:
        print_error("PostgreSQL password is required for restore operations")
        return False
    
    # Collect customer name (optional)
    print_info("\n--- Customer Name (optional) ---")
    print_info("Customer name will be displayed prominently in email alerts")
    customer_name = input(f"{Colors.OKCYAN}Customer name (for email alerts): {Colors.ENDC}").strip()
    
    # Collect Alfresco user
    real_user, real_uid, real_gid = get_real_user()
    print_info("\n--- Alfresco OS User ---")
    alfresco_user = input(f"{Colors.OKCYAN}Alfresco OS user [{real_user}]: {Colors.ENDC}").strip() or real_user
    
    # Write .env file for restore
    env_content = f"""# Restore Configuration
# PostgreSQL Configuration
PGHOST={pg_host}
PGPORT={pg_port}
PGUSER={pg_user}
PGPASSWORD={pg_password}
PGDATABASE={pg_database}

# Path Configuration
# BACKUP_DIR is only required for local backups (not needed for S3 backups)
# Leave empty if using S3 restore
BACKUP_DIR={backup_dir if backup_dir else ''}
EISENVAULT_RESTORE_DIR={alf_base_dir}
# Optional legacy fallback. Set only if source and restore are the same installation.
#ALF_BASE_DIR={alf_base_dir}

# S3 Backup Configuration (optional)
# If S3_BUCKET is set, restore will download backups from S3
# Requires rclone to be installed: https://rclone.org/install/
S3_BUCKET={s3_bucket if s3_bucket else ''}
S3_REGION={s3_region if s3_region else ''}
AWS_ACCESS_KEY_ID={aws_access_key_id if aws_access_key_id else ''}
AWS_SECRET_ACCESS_KEY={aws_secret_access_key if aws_secret_access_key else ''}

# Customer Name (optional, displayed prominently in email alerts)
CUSTOMER_NAME={customer_name}

# Alfresco OS User
ALFRESCO_USER={alfresco_user}
"""
    
    with open(env_file, 'w') as f:
        f.write(env_content)
    
    # Set ownership if running as root
    if is_running_as_root():
        os.chown(env_file, real_uid, real_gid)
    
    os.chmod(env_file, 0o600)  # Secure the file
    
    print_success(f"\n.env file created at: {env_file.absolute()}")
    print_success("File permissions set to 600 (read/write for owner only)")
    
    return True

def setup_restore_only():
    """Simplified setup flow for restore operations only."""
    print_header("Alfresco Restore System - Quick Setup")
    
    real_user, real_uid, real_gid = get_real_user()
    running_as_root = is_running_as_root()
    
    if running_as_root:
        print_info(f"Running with sudo privileges (real user: {real_user})")
        print_info("All files and directories will be owned by the real user.")
    else:
        print_info(f"Running as user: {real_user}")
    
    print_info("\nThis simplified setup will:")
    print_info("  1. Check prerequisites (Python 3)")
    print_info("  2. Create a Python virtual environment")
    print_info("  3. Install required dependencies")
    print_info("  4. Configure restore settings in .env file (PostgreSQL, paths, user)")
    print_info("\nThe restore script will use settings from .env file automatically.\n")
    
    if not ask_yes_no("Start restore setup?"):
        print_info("Setup canceled.")
        sys.exit(0)
    
    # Check prerequisites (simplified for restore)
    if not check_prerequisites(for_restore=True):
        print_info("Setup canceled.")
        sys.exit(0)
    
    print_header("Install Python Dependencies")
    if not install_python_dependencies():
        print_error("Failed to install Python dependencies in venv")
        sys.exit(1)
    
    # Create minimal .env file with PostgreSQL credentials
    if not create_restore_env_file():
        print_warning("Continuing without .env file. Restore operations may fail without PostgreSQL credentials.")
    
    print_header("Restore Setup Complete!")
    print_info("\nVirtual environment created and dependencies installed")
    if Path('.env').exists():
        print_info("Restore configuration saved to .env file:")
        print_info("  - PostgreSQL credentials")
        print_info("  - Backup directory path")
        print_info("  - EisenVault source folder path")
        print_info("  - Alfresco OS user")
    print_info("\nYou can now run the restore script:")
    print_info("  python restore.py")
    print_info("\nThe restore script will use configuration from .env file.")
    print_info("If .env is missing or incomplete, it will prompt for missing values.")
    print_info("\nSee docs/operations/restore-runbook.md for detailed restore procedures.")

def venv_python() -> Path:
    return Path.cwd() / 'venv' / 'bin' / 'python'


def venv_pip() -> Path:
    return Path.cwd() / 'venv' / 'bin' / 'pip'


def install_python_dependencies() -> bool:
    """Install requirements into project venv (avoids PEP 668 system pip errors)."""
    print_header("Install Python Dependencies (virtual environment)")
    print_warning(
        "Do not run: pip install -r requirements.txt\n"
        "On Ubuntu/Debian the system Python is externally managed.\n"
        "This installer uses: venv/bin/pip"
    )
    if not create_virtual_environment():
        return False
    if not add_venv_site_packages():
        print_error("Could not load venv site-packages into setup.py")
        return False
    if not python_dependencies_available():
        pip = venv_pip()
        if not pip.exists():
            print_error(f"venv pip not found: {pip}")
            return False
        real_user, _, _ = get_real_user()
        if is_running_as_root():
            result = run_command(['sudo', '-u', real_user, str(pip), 'install', '-r', 'requirements.txt'], check=False)
        else:
            result = run_command([str(pip), 'install', '-r', 'requirements.txt'], check=False)
        if not result or result.returncode != 0:
            print_error("Failed to install dependencies")
            return False
        add_venv_site_packages()
        if not python_dependencies_available():
            print_error("Dependencies installed but setup.py still cannot import them")
            return False
    print_success("Dependencies installed in venv")
    print_info(f"Run backups with: {venv_python()} backup.py")
    return True


def python_dependencies_available() -> bool:
    try:
        import dotenv  # noqa: F401
        import yaml  # noqa: F401
        import tqdm  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_restic() -> bool:
    if shutil.which('restic'):
        print_success("restic is installed")
        return True
    print_warning("restic is not installed")
    if ask_yes_no("Install restic via apt?", default=True):
        prefix = [] if is_running_as_root() else ['sudo']
        update = run_command(prefix + ['apt-get', 'update'], capture_output=True, check=False)
        install = run_command(prefix + ['apt-get', 'install', '-y', 'restic'], capture_output=True, check=False)
        if update and install and install.returncode == 0 and shutil.which('restic'):
            print_success("restic installed")
            return True
        print_warning("restic is not available from this system's apt repositories")
    if ask_yes_no(
        "Install the verified official restic binary to /usr/local/bin?", default=True
    ):
        installed, message = install_restic_release(use_sudo=not is_running_as_root())
        if installed:
            print_success(message)
            return True
        print_error(message)
    return False


def create_base_env_file() -> bool:
    """Create .env with PostgreSQL, Alfresco paths, and email (no legacy backup dirs)."""
    print_header("Host and Database Configuration (.env)")
    env_file = Path('.env')
    if env_file.exists():
        print_info(f".env exists at {env_file.absolute()}")
        if not ask_yes_no("Reconfigure .env?", default=False):
            return True

    print_info("\n--- Alfresco Base Directory ---")
    while True:
        alf_base_dir = input(f"{Colors.OKCYAN}EisenVault source folder path: {Colors.ENDC}").strip()
        if alf_base_dir and Path(alf_base_dir).exists():
            break
        print_error(f"Directory does not exist: {alf_base_dir}")

    print_info("\n--- Database Configuration ---")
    db_settings = detect_db_settings_from_alfresco(alf_base_dir)
    if db_settings:
        print_success("Auto-detected database settings from alfresco-global.properties")
        use_detected = ask_yes_no("Use detected settings?", default=True)
        if use_detected:
            pg_host = db_settings.get('host', 'localhost')
            pg_port = db_settings.get('port', '5432')
            pg_user = db_settings.get('user', 'alfresco')
            pg_password = db_settings.get('password', '')
            pg_database = db_settings.get('database', 'postgres')
        else:
            pg_host = input(f"{Colors.OKCYAN}PostgreSQL host [localhost]: {Colors.ENDC}").strip() or 'localhost'
            pg_port = input(f"{Colors.OKCYAN}PostgreSQL port [5432]: {Colors.ENDC}").strip() or '5432'
            pg_user = input(f"{Colors.OKCYAN}PostgreSQL user [alfresco]: {Colors.ENDC}").strip() or 'alfresco'
            pg_password = input(f"{Colors.OKCYAN}PostgreSQL password: {Colors.ENDC}").strip()
            pg_database = input(f"{Colors.OKCYAN}PostgreSQL database [postgres]: {Colors.ENDC}").strip() or 'postgres'
    else:
        pg_host = input(f"{Colors.OKCYAN}PostgreSQL host [localhost]: {Colors.ENDC}").strip() or 'localhost'
        pg_port = input(f"{Colors.OKCYAN}PostgreSQL port [5432]: {Colors.ENDC}").strip() or '5432'
        pg_user = input(f"{Colors.OKCYAN}PostgreSQL user [alfresco]: {Colors.ENDC}").strip() or 'alfresco'
        pg_password = input(f"{Colors.OKCYAN}PostgreSQL password: {Colors.ENDC}").strip()
        pg_database = input(f"{Colors.OKCYAN}PostgreSQL database [postgres]: {Colors.ENDC}").strip() or 'postgres'

    pg_superuser = input(
        f"{Colors.OKCYAN}PostgreSQL superuser [{pg_user}]: {Colors.ENDC}"
    ).strip() or pg_user
    customer_name = input(f"{Colors.OKCYAN}Customer name (optional): {Colors.ENDC}").strip()

    print_info("\n--- Email Alerts (optional) ---")
    configure_email = ask_yes_no("Configure email alerts?", default=False)
    if configure_email:
        email_alert_mode = input(f"{Colors.OKCYAN}Mode (both/failure_only/none) [failure_only]: {Colors.ENDC}").strip() or 'failure_only'
        smtp_host = input(f"{Colors.OKCYAN}SMTP host [smtp.gmail.com]: {Colors.ENDC}").strip() or 'smtp.gmail.com'
        smtp_port = input(f"{Colors.OKCYAN}SMTP port [587]: {Colors.ENDC}").strip() or '587'
        smtp_user = input(f"{Colors.OKCYAN}SMTP username: {Colors.ENDC}").strip()
        smtp_password = input(f"{Colors.OKCYAN}SMTP password: {Colors.ENDC}").strip()
        alert_email = input(f"{Colors.OKCYAN}Alert recipient: {Colors.ENDC}").strip()
        alert_from = input(f"{Colors.OKCYAN}From address [{smtp_user}]: {Colors.ENDC}").strip() or smtp_user
    else:
        email_alert_mode = 'failure_only'
        smtp_host = smtp_port = smtp_user = smtp_password = alert_email = alert_from = ''

    env_content = f"""# Database Configuration
PGHOST={pg_host}
PGPORT={pg_port}
PGUSER={pg_user}
PGPASSWORD={pg_password}
PGDATABASE={pg_database}
PGSUPERUSER={pg_superuser}

# EisenVault paths
EISENVAULT_SOURCE_DIR={alf_base_dir}
EISENVAULT_RESTORE_DIR={alf_base_dir}
# Legacy fallback for older scripts/configs
ALF_BASE_DIR={alf_base_dir}

# Customer name (optional, email subject)
CUSTOMER_NAME={customer_name}

# Email Alerts
EMAIL_ALERT_MODE={email_alert_mode}
SMTP_HOST={smtp_host}
SMTP_PORT={smtp_port}
SMTP_USER={smtp_user}
SMTP_PASSWORD={smtp_password}
ALERT_EMAIL={alert_email}
ALERT_FROM={alert_from}

# Restic / object storage secrets go here (see backup-policies.yml *_env names)
"""
    with open(env_file, 'w') as f:
        f.write(env_content)
    if is_running_as_root():
        real_user, real_uid, real_gid = get_real_user()
        os.chown(env_file, real_uid, real_gid)
    os.chmod(env_file, 0o600)
    print_success(f".env written to {env_file.absolute()}")
    return True


def setup_single_destination() -> None:
    print_header("Initial Setup: Single Restic Destination")
    if not check_prerequisites(for_restore=False):
        return
    if not ensure_restic():
        return
    if not install_python_dependencies():
        return
    if not create_base_env_file():
        return
    from alfresco_backup.v2.setup_menu import create_single_destination_policy
    create_single_destination_policy(Path('backup-policies.yml'), Path('.env'))
    configure_cron_job()
    verify_installation()


def setup_multiple_destinations() -> None:
    print_header("Initial Setup: Multiple Restic Destinations")
    if not check_prerequisites(for_restore=False):
        return
    if not ensure_restic():
        return
    if not install_python_dependencies():
        return
    if not create_base_env_file():
        return
    from alfresco_backup.v2.setup_menu import create_multiple_destinations_policy
    create_multiple_destinations_policy(Path('backup-policies.yml'), Path('.env'))
    configure_cron_job()
    verify_installation()


def guided_initial_setup() -> None:
    print_header("Guided Backup Setup")
    print_info("This will automatically check prerequisites, create the venv, install dependencies, and check restic.")

    if not check_prerequisites(for_restore=False):
        return
    if not install_python_dependencies():
        return
    if not ensure_restic():
        return
    if not create_base_env_file():
        return

    print("\nBackup destination mode:")
    print("  1. One destination")
    print("  2. Multiple destinations")
    mode = input(f"{Colors.OKCYAN}Choice [1]: {Colors.ENDC}").strip() or '1'

    if mode == '2':
        from alfresco_backup.v2.setup_menu import create_multiple_destinations_policy
        create_multiple_destinations_policy(Path('backup-policies.yml'), Path('.env'))
    else:
        from alfresco_backup.v2.setup_menu import create_single_destination_policy
        create_single_destination_policy(Path('backup-policies.yml'), Path('.env'))

    if ask_yes_no("Configure automated backup cron now?", default=True):
        configure_cron_job()
    verify_installation()


def run_backup_now() -> None:
    print_header("Run Backup Now")
    py = venv_python()
    if not py.exists():
        print_error("Virtual environment missing. Run Guided setup first.")
        return
    print_info("Running all enabled destinations immediately...")
    result = run_command(
        [str(py), '-c', 'from alfresco_backup.v2.__main__ import main; main(force_all_destinations=True)'],
        check=False,
        quiet=True,
    )
    if result and result.returncode == 0:
        print_success("Backup run completed")
    elif result and result.returncode == 2:
        print_warning("Backup completed with partial success (see log above)")
    elif result:
        print_error(f"Backup failed (exit {result.returncode}). See log above.")
    log_file = Path('/var/tmp/alfresco-backup/logs')
    if log_file.exists():
        latest = sorted(log_file.glob('backup-*.log'))
        if latest:
            print_info(f"Log file: {latest[-1]}")


def run_main_menu() -> None:
    print_header("Alfresco Backup Setup")
    real_user, _, _ = get_real_user()
    print_info(f"User: {real_user}")
    print_info("Backups use restic only (see backup-policies.yml for destinations).")
    print_warning("Do not use system pip. Setup installs packages into ./venv.")

    while True:
        print("\nMain menu:")
        print("  1. Guided setup")
        print("  2. Manage backup destinations")
        print("  3. Run backup now")
        print("  4. Restore-only setup")
        print("  5. Verify installation")
        print("  0. Exit")
        choice = input(f"{Colors.OKCYAN}Choice: {Colors.ENDC}").strip()

        if choice == '0':
            print_info("Goodbye.")
            break
        elif choice == '1':
            guided_initial_setup()
        elif choice == '2':
            if not python_dependencies_available() and not install_python_dependencies():
                continue
            from alfresco_backup.v2.setup_menu import manage_destinations_menu
            manage_destinations_menu()
        elif choice == '3':
            run_backup_now()
        elif choice == '4':
            setup_restore_only()
        elif choice == '5':
            verify_installation()
        else:
            print_warning("Invalid choice")


def main():
    """Interactive setup (no command-line flags)."""
    run_main_menu()

def ensure_replication_privilege_for_alfresco(
    pg_data_dir: str, psql_bin: str, pg_ctl_bin: str
):
    """Ensure 'alfresco' user has REPLICATION privilege even in TCP-only mode."""
    import shutil
    import subprocess
    import time

    pg_hba = Path(pg_data_dir) / "pg_hba.conf"
    if not pg_hba.exists():
        print_error(f"pg_hba.conf not found at {pg_hba}")
        return False

    backup_file = pg_hba.with_suffix(f".bak.auto.{int(time.time())}")
    shutil.copy2(pg_hba, backup_file)
    print_success(f"Backed up pg_hba.conf → {backup_file}")

    content = pg_hba.read_text().splitlines()
    patched = []
    inserted = False
    for line in content:
        if not inserted and "host" in line and "127.0.0.1/32" in line and "md5" in line:
            patched.append("host    all             postgres        127.0.0.1/32            trust")
            inserted = True
        patched.append(line)
    if not inserted:
        patched.insert(0, "host    all             postgres        127.0.0.1/32            trust")

    pg_hba.write_text("\n".join(patched) + "\n")
    subprocess.run([pg_ctl_bin, "-D", pg_data_dir, "reload"], check=False)
    print_info("PostgreSQL configuration reloaded with temporary trust rule.")

    grant_cmd = [
        psql_bin,
        "-h",
        "127.0.0.1",
        "-U",
        "postgres",
        "-d",
        "postgres",
        "-c",
        "ALTER USER alfresco WITH REPLICATION;",
    ]
    result = subprocess.run(grant_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print_error(f"Grant failed: {result.stderr.strip()}")
        return False
    print_success("ALTER USER executed successfully.")

    verify_cmd = [
        psql_bin,
        "-h",
        "127.0.0.1",
        "-U",
        "postgres",
        "-d",
        "postgres",
        "-t",
        "-A",
        "-c",
        "SELECT rolreplication FROM pg_roles WHERE rolname='alfresco';",
    ]
    verify = subprocess.run(verify_cmd, capture_output=True, text=True)
    if verify.returncode == 0 and verify.stdout.strip() == "t":
        print_success("Replication privilege verified (rolreplication = t).")
    else:
        print_error("Replication verification failed.")
        print_info(verify.stdout.strip())
        return False

    cleaned = [
        line
        for line in patched
        if "postgres        127.0.0.1/32            trust" not in line
    ]
    pg_hba.write_text("\n".join(cleaned) + "\n")
    subprocess.run([pg_ctl_bin, "-D", pg_data_dir, "reload"], check=False)
    print_success("Temporary trust rule removed, pg_hba.conf restored.")
    return True

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print_info("\n\nSetup interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print_error(f"\nUnexpected error: {e}")
        sys.exit(1)
