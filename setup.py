#!/usr/bin/env python3
"""
Interactive setup script for Alfresco Large Content Store Backup System.
Run this script after cloning the repository to set up all required configurations.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
from typing import Optional

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
    """Run a shell command."""
    try:
        if capture_output:
            result = subprocess.run(cmd, capture_output=True, text=True, check=check)
            return result
        else:
            subprocess.run(cmd, check=check)
            return None
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {' '.join(cmd)}")
        if capture_output and e.stderr:
            print_error(f"Error: {e.stderr}")
        return None
    except FileNotFoundError:
        print_error(f"Command not found: {cmd[0]}")
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
    
    print_info(f"This will create the following directory structure:")
    print_info(f"  {backup_dir}/")
    print_info(f"  ├── postgres/")
    print_info(f"  ├── contentstore/")
    print_info(f"  └── pg_wal/")
    print_info(f"\nAll directories will be owned by the current user: {os.getenv('USER')}")
    
    if not ask_yes_no("\nCreate backup directories?"):
        print_warning("Skipping directory creation")
        return False
    
    try:
        # Create main backup directory
        Path(backup_dir).mkdir(parents=True, exist_ok=True)
        print_success(f"Created: {backup_dir}")
        
        # Create subdirectories
        for subdir in ['postgres', 'contentstore', 'pg_wal']:
            path = Path(backup_dir) / subdir
            path.mkdir(exist_ok=True)
            print_success(f"Created: {path}")
        
        # Set ownership if we have sudo and it's not already owned by current user
        current_user = os.getenv('USER')
        stat_info = os.stat(backup_dir)
        
        if stat_info.st_uid != os.getuid():
            print_info(f"\nDirectory is not owned by {current_user}. Setting ownership...")
            if ask_yes_no("Run 'sudo chown' to set ownership?"):
                result = run_command(['sudo', 'chown', '-R', f'{current_user}:{current_user}', backup_dir])
                if result is not None:
                    print_success(f"Set ownership to {current_user}")
        
        return True
        
    except PermissionError as e:
        print_error(f"Permission denied: {e}")
        print_info(f"\nTry running: sudo mkdir -p {backup_dir} && sudo chown -R $USER:$USER {backup_dir}")
        return False
    except Exception as e:
        print_error(f"Error creating directories: {e}")
        return False

def configure_wal_archive():
    """Help configure WAL archive directory for PostgreSQL."""
    print_header("Step 4: Configure WAL Archive Directory for PostgreSQL")
    
    config = load_env_config()
    backup_dir = config.get('BACKUP_DIR')
    
    if not backup_dir:
        print_error("BACKUP_DIR not found in .env file")
        return False
    
    wal_dir = Path(backup_dir) / 'pg_wal'
    
    print_info("PostgreSQL needs write access to the WAL archive directory.")
    print_info(f"WAL directory: {wal_dir}")
    print_info(f"\nThis will:")
    print_info(f"  1. Set ownership to postgres:{os.getenv('USER')}")
    print_info(f"  2. Set permissions to 770 (rwxrwx---)")
    print_info(f"  3. Allow both PostgreSQL and {os.getenv('USER')} to access the directory")
    
    if not ask_yes_no("\nConfigure WAL directory permissions?"):
        print_warning("Skipping WAL directory configuration")
        print_warning("You will need to configure this manually for backups to work")
        return False
    
    try:
        current_user = os.getenv('USER')
        
        # Change ownership
        print_info(f"\nRunning: sudo chown postgres:{current_user} {wal_dir}")
        result = run_command(['sudo', 'chown', f'postgres:{current_user}', str(wal_dir)], check=False)
        if result is None:
            print_success(f"Set ownership to postgres:{current_user}")
        
        # Change permissions
        print_info(f"Running: sudo chmod 770 {wal_dir}")
        result = run_command(['sudo', 'chmod', '770', str(wal_dir)], check=False)
        if result is None:
            print_success("Set permissions to 770")
        
        return True
        
    except Exception as e:
        print_error(f"Error configuring WAL directory: {e}")
        return False

def show_postgresql_config():
    """Show PostgreSQL configuration instructions."""
    print_header("Step 5: PostgreSQL Configuration")
    
    config = load_env_config()
    backup_dir = config.get('BACKUP_DIR')
    
    if not backup_dir:
        print_error("BACKUP_DIR not found in .env file")
        return False
    
    wal_dir = Path(backup_dir) / 'pg_wal'
    
    print_info("PostgreSQL must be configured for WAL archiving.")
    print_info("This requires editing postgresql.conf and pg_hba.conf files.")
    print_info("\nThese changes require PostgreSQL restart and should be reviewed carefully.")
    
    if not ask_yes_no("\nShow PostgreSQL configuration instructions?"):
        print_warning("Skipping PostgreSQL configuration instructions")
        return False
    
    print_info("\n" + "="*80)
    print_info("POSTGRESQL.CONF SETTINGS")
    print_info("="*80)
    
    print_info("\n1. Find your postgresql.conf file:")
    print("   sudo -u postgres psql -c \"SHOW config_file;\"")
    
    print_info("\n2. Add or modify these settings:")
    print(f"""
   wal_level = replica
   archive_mode = on
   archive_command = 'test ! -f {wal_dir}/%f && cp %p {wal_dir}/%f'
   max_wal_senders = 3
   wal_keep_size = 1GB
""")
    
    print_info("\n" + "="*80)
    print_info("PG_HBA.CONF SETTINGS")
    print_info("="*80)
    
    print_info("\n1. Find your pg_hba.conf file:")
    print("   sudo -u postgres psql -c \"SHOW hba_file;\"")
    
    print_info("\n2. Add this line to allow replication connections:")
    pg_user = config.get('PGUSER', 'alfresco')
    print(f"   local   replication     {pg_user}                                md5")
    
    print_info("\n" + "="*80)
    print_info("GRANT REPLICATION PRIVILEGE")
    print_info("="*80)
    
    print_info("\nGrant replication privilege to your backup user:")
    print(f"   sudo -u postgres psql -c \"ALTER USER {pg_user} REPLICATION;\"")
    
    print_info("\n" + "="*80)
    print_info("RESTART POSTGRESQL")
    print_info("="*80)
    
    print_info("\nAfter making changes, restart PostgreSQL:")
    print("   sudo systemctl restart postgresql")
    print("   sudo systemctl status postgresql")
    
    print_warning("\n⚠ Important: These changes must be made manually by a database administrator.")
    print_warning("⚠ The backup script will validate these settings before running.")
    
    return True

def create_virtual_environment():
    """Create Python virtual environment and install dependencies."""
    print_header("Step 6: Create Virtual Environment")
    
    venv_path = Path('venv')
    
    print_info("Creating a Python virtual environment isolates dependencies.")
    print_info(f"Virtual environment will be created at: {venv_path.absolute()}")
    
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
        result = run_command([sys.executable, '-m', 'venv', 'venv'])
        if result is None:
            print_success("Virtual environment created")
        else:
            return False
        
        # Determine pip path
        pip_path = venv_path / 'bin' / 'pip'
        
        # Install dependencies
        print_info("\nInstalling dependencies from requirements.txt...")
        result = run_command([str(pip_path), 'install', '-r', 'requirements.txt'])
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
    
    print_info("This wizard will guide you through setting up the backup system.")
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
    
    # Step 5: Show PostgreSQL configuration
    show_postgresql_config()
    
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

