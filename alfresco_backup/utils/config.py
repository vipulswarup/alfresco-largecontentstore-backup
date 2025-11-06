"""Configuration loader for Alfresco backup system."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv


class BackupConfig:
    """Load and validate configuration from .env file."""
    
    def __init__(self, env_file=None):
        """Load configuration from environment file."""
        if env_file:
            if not os.path.exists(env_file):
                raise FileNotFoundError(f"Environment file not found: {env_file}")
            load_dotenv(env_file)
        else:
            load_dotenv()
        
        self._load_and_validate()
    
    def _load_and_validate(self):
        """Load environment variables and validate required fields."""
        required_vars = [
            'PGHOST', 'PGPORT', 'PGUSER', 'PGPASSWORD',
            'BACKUP_DIR', 'ALF_BASE_DIR', 'RETENTION_DAYS'
        ]
        optional_email_vars = [
            'SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASSWORD',
            'ALERT_EMAIL', 'ALERT_FROM'
        ]
        
        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
            sys.exit(1)
        
        missing_email = [var for var in optional_email_vars if not os.getenv(var)]
        self.email_enabled = len(missing_email) == 0
        if missing_email:
            print(
                "WARNING: Email alerts disabled due to missing variables: "
                + ', '.join(missing_email)
            )
        
        # Database settings
        self.pghost = os.getenv('PGHOST')
        self.pgport = os.getenv('PGPORT')
        self.pguser = os.getenv('PGUSER')
        self.pgpassword = os.getenv('PGPASSWORD')
        self.pgdatabase = os.getenv('PGDATABASE', 'postgres')
        self.pgsuperuser = os.getenv('PGSUPERUSER', 'postgres')
        
        # Path settings
        self.backup_dir = Path(os.getenv('BACKUP_DIR'))
        self.alf_base_dir = Path(os.getenv('ALF_BASE_DIR'))
        
        # Retention settings
        try:
            self.retention_days = int(os.getenv('RETENTION_DAYS'))
        except ValueError:
            print("ERROR: RETENTION_DAYS must be an integer")
            sys.exit(1)
        
        # Customer name (optional, for email alerts)
        self.customer_name = os.getenv('CUSTOMER_NAME', '').strip()
        
        # Contentstore backup timeout (optional, in seconds, default 24 hours)
        try:
            timeout_hours = int(os.getenv('CONTENTSTORE_TIMEOUT_HOURS', '24'))
            self.contentstore_timeout = timeout_hours * 3600
        except ValueError:
            print("WARNING: Invalid CONTENTSTORE_TIMEOUT_HOURS, using 24 hours")
            self.contentstore_timeout = 86400
        
        # Email settings
        email_alert_mode = os.getenv('EMAIL_ALERT_MODE', 'failure_only').lower()
        if email_alert_mode not in ['both', 'failure_only', 'none']:
            print(f"WARNING: Invalid EMAIL_ALERT_MODE '{email_alert_mode}', using 'failure_only'")
            email_alert_mode = 'failure_only'
        self.email_alert_mode = email_alert_mode
        
        # If mode is "none", treat as if email is disabled
        if email_alert_mode == 'none':
            self.email_enabled = False
        
        if self.email_enabled:
            self.smtp_host = os.getenv('SMTP_HOST')
            self.smtp_port = int(os.getenv('SMTP_PORT'))
            self.smtp_user = os.getenv('SMTP_USER')
            self.smtp_password = os.getenv('SMTP_PASSWORD')
            self.alert_email = os.getenv('ALERT_EMAIL')
            self.alert_from = os.getenv('ALERT_FROM')
        else:
            self.smtp_host = None
            self.smtp_port = None
            self.smtp_user = None
            self.smtp_password = None
            self.alert_email = None
            self.alert_from = None
        
        # Validate paths
        if not self.backup_dir.exists():
            print(f"ERROR: Backup directory does not exist: {self.backup_dir}")
            sys.exit(1)
        
        if not self.alf_base_dir.exists():
            print(f"ERROR: Alfresco base directory does not exist: {self.alf_base_dir}")
            sys.exit(1)
        
        contentstore = self.alf_base_dir / 'alf_data' / 'contentstore'
        if not contentstore.exists():
            print(f"ERROR: Contentstore directory does not exist: {contentstore}")
            sys.exit(1)

