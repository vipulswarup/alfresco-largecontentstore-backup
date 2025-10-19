# Alfresco Backup System

Python-based backup system for Alfresco Content Management System with PostgreSQL and contentstore backups.

## Features

- PostgreSQL WAL configuration validation (validates archiving is enabled)
- PostgreSQL base backup using pg_basebackup
- Contentstore rsync with hardlink optimization for space efficiency
- WAL archive monitoring
- Automated retention policy enforcement
- Email alerts on failures with detailed error information
- File-based locking to prevent concurrent executions
- Comprehensive logging

## Requirements

- Python 3.7+
- PostgreSQL client tools (pg_basebackup)
- rsync
- Sufficient disk space for backups

## Quick Installation (Recommended)

### Automated Setup Script

The easiest way to set up the backup system is using the interactive setup script:

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/alfresco-largecontentstore-backup.git
cd alfresco-largecontentstore-backup

# Run the setup wizard
python3 setup.py
```

The setup script will:
- Check if all required tools are installed
- Help you create the `.env` configuration file
- Create all necessary backup directories (will prompt for sudo if needed)
- Configure proper permissions for WAL archiving (will prompt for sudo)
- Show PostgreSQL configuration instructions
- Create a virtual environment and install dependencies
- Verify the installation

**Important:**
- Run this as the same user that runs Alfresco (not root)
- You will need sudo access for creating directories in `/mnt/backups` and setting PostgreSQL permissions
- The script asks permission before each step and explains what it will do

After setup completes, you'll need to configure PostgreSQL manually (the script provides exact instructions).

---

## Manual Installation on Ubuntu

If you prefer to set up manually or need more control, follow these steps:

### Step 1: Update System Packages
```bash
sudo apt-get update
```

### Step 2: Install Python 3 and pip
```bash
sudo apt-get install -y python3 python3-pip python3-venv
```

### Step 3: Install PostgreSQL Client Tools
```bash
# Install PostgreSQL client tools (includes pg_basebackup)
sudo apt-get install -y postgresql-client

# Verify installation
pg_basebackup --version
```

### Step 4: Install rsync
```bash
sudo apt-get install -y rsync

# Verify installation
rsync --version
```

### Step 5: Clone or Download This Repository
```bash
# Clone as your Alfresco user (not root)
cd /opt
sudo mkdir -p alfresco-largecontentstore-backup
sudo chown $USER:$USER alfresco-largecontentstore-backup
git clone https://github.com/YOUR_USERNAME/alfresco-largecontentstore-backup.git
cd alfresco-largecontentstore-backup

# Ensure the directory is owned by the current user
sudo chown -R $USER:$USER /opt/alfresco-largecontentstore-backup
```

### Step 6: Create Virtual Environment (Recommended)
```bash
# Create venv as regular user (NOT with sudo)
python3 -m venv venv
source venv/bin/activate
```

### Step 7: Install Python Dependencies
```bash
# Install packages in the virtual environment (no sudo needed)
pip install -r requirements.txt
```

### Step 8: Create Backup Directory
```bash
# Create backup directory owned by current user
sudo mkdir -p /mnt/backups/alfresco
sudo chown -R $USER:$USER /mnt/backups/alfresco
sudo chmod 755 /mnt/backups/alfresco
```

### Step 9: Configure Environment Variables

Create your `.env` file from the example:
```bash
# Copy and edit with your actual values
cat > .env << 'EOF'
# Database Configuration
PGHOST=localhost
PGPORT=5432
PGUSER=alfresco
PGPASSWORD=your_db_password_here

# Paths
BACKUP_DIR=/mnt/backups/alfresco
ALF_BASE_DIR=/opt/alfresco

# Retention Policy
RETENTION_DAYS=30

# Email Alerts (only sent on failures)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=backups@yourcompany.com
SMTP_PASSWORD=your_email_password_here
ALERT_EMAIL=ops-team@yourcompany.com
ALERT_FROM=backups@yourcompany.com
EOF
```

### Step 10: Set File Permissions
```bash
# Make the backup script executable
chmod +x backup.py

# Secure your .env file
chmod 600 .env
```

### Step 11: Verify Installation
```bash
# Test that all tools are available
python3 --version
pg_basebackup --version
rsync --version

# Test the backup script help
python3 backup.py --help 2>/dev/null || echo "Ready to configure and run backups"
```

## Usage

### Running Backups Manually

If using virtual environment:
```bash
cd /opt/alfresco-largecontentstore-backup
source venv/bin/activate
python backup.py
```

Or specify a custom env file location:
```bash
python backup.py /path/to/custom.env
```

### Scheduling with Cron

**Important:** Run cron jobs as the same user that runs Alfresco (not root). This ensures proper file permissions.

For daily backups at 2 AM, add to crontab:

**If using virtual environment:**
```bash
# Edit crontab as the Alfresco user (NOT using sudo crontab)
crontab -e

# Add this line (adjust paths if needed):
0 2 * * * cd /opt/alfresco-largecontentstore-backup && /opt/alfresco-largecontentstore-backup/venv/bin/python /opt/alfresco-largecontentstore-backup/backup.py >> /var/log/alfresco-backup-cron.log 2>&1
```

**If installed system-wide:**
```bash
# Edit crontab as the Alfresco user (NOT using sudo crontab)
crontab -e

# Add this line:
0 2 * * * cd /opt/alfresco-largecontentstore-backup && python3 backup.py >> /var/log/alfresco-backup-cron.log 2>&1
```

**Create the log file with proper permissions:**
```bash
sudo touch /var/log/alfresco-backup-cron.log
sudo chown $USER:$USER /var/log/alfresco-backup-cron.log
sudo chmod 644 /var/log/alfresco-backup-cron.log
```

## What Gets Backed Up

1. **PostgreSQL Database**: Full base backup using pg_basebackup in compressed tar format
2. **Contentstore**: All files in `ALF_BASE_DIR/contentstore` using rsync with hardlinks
3. **WAL Files**: Monitored in `BACKUP_DIR/pg_wal` for PITR capability

## PostgreSQL WAL Configuration Requirements

Before backups can run, PostgreSQL must be properly configured for WAL (Write-Ahead Log) archiving to enable Point-in-Time Recovery (PITR).

### Step 1: Locate PostgreSQL Configuration File

The script checks for `postgresql.conf` in these locations:
1. `ALF_BASE_DIR/alf_data/postgresql/postgresql.conf`
2. `ALF_BASE_DIR/postgresql/postgresql.conf`

For standard PostgreSQL installations on Ubuntu, find your config file:
```bash
# Find postgresql.conf location
sudo -u postgres psql -c "SHOW config_file;"

# Or search for it
sudo find / -name postgresql.conf 2>/dev/null | grep -v snap
```

### Step 2: Create WAL Archive Directory

```bash
# Create WAL archive directory (must match BACKUP_DIR/pg_wal in your .env)
sudo mkdir -p /mnt/backups/alfresco/pg_wal

# Make it writable by both postgres (for archiving) and your user (for monitoring)
sudo chown postgres:$USER /mnt/backups/alfresco/pg_wal
sudo chmod 770 /mnt/backups/alfresco/pg_wal
```

### Step 3: Edit PostgreSQL Configuration

**Required settings:**

```bash
# Edit postgresql.conf (use the path from Step 1)
sudo nano /etc/postgresql/14/main/postgresql.conf
```

Add or modify these settings:

```conf
# WAL archiving settings
wal_level = replica                    # or 'logical' (NOT 'minimal')
archive_mode = on                      # Enable archiving
archive_command = 'test ! -f /mnt/backups/alfresco/pg_wal/%f && cp %p /mnt/backups/alfresco/pg_wal/%f'
archive_timeout = 300                  # Force WAL switch every 5 minutes (optional)

# Recommended additional settings for backup
max_wal_senders = 3                    # Allow pg_basebackup connections
wal_keep_size = 1GB                    # Keep extra WAL for safety (PostgreSQL 13+)
# OR for PostgreSQL 12 and earlier:
# wal_keep_segments = 64
```

**Important Notes:**
- Replace `/mnt/backups/alfresco/pg_wal` with your actual `BACKUP_DIR/pg_wal` path
- The `test ! -f` prevents overwriting existing WAL files
- `%p` is the path of the file to archive
- `%f` is the file name only

### Step 4: Configure PostgreSQL Authentication (for pg_basebackup)

Edit `pg_hba.conf` to allow replication connections:

```bash
# Find pg_hba.conf location
sudo -u postgres psql -c "SHOW hba_file;"

# Edit the file
sudo nano /etc/postgresql/14/main/pg_hba.conf
```

Add this line (adjust based on your setup):

```conf
# TYPE  DATABASE        USER            ADDRESS                 METHOD
# For local backups using unix socket
local   replication     alfresco                                md5
# Or for network backups
host    replication     alfresco        127.0.0.1/32            md5
host    replication     alfresco        ::1/128                 md5
```

### Step 5: Restart PostgreSQL

```bash
# Restart PostgreSQL to apply changes
sudo systemctl restart postgresql

# Verify PostgreSQL is running
sudo systemctl status postgresql
```

### Step 6: Verify WAL Configuration

```bash
# Check WAL settings
sudo -u postgres psql -c "SHOW wal_level;"
sudo -u postgres psql -c "SHOW archive_mode;"
sudo -u postgres psql -c "SHOW archive_command;"

# Expected output:
# wal_level      | replica (or logical)
# archive_mode   | on
# archive_command| test ! -f /mnt/backups/alfresco/pg_wal/%f && cp %p /mnt/backups/alfresco/pg_wal/%f
```

### Step 7: Test WAL Archiving

```bash
# Force a WAL segment switch and verify archiving works
sudo -u postgres psql -c "SELECT pg_switch_wal();"  # PostgreSQL 10+
# OR for PostgreSQL 9.6 and earlier:
# sudo -u postgres psql -c "SELECT pg_switch_xlog();"

# Check if WAL files are being archived
ls -lh /mnt/backups/alfresco/pg_wal/

# You should see WAL files like: 000000010000000000000001
```

### Step 8: Verify pg_basebackup Access

```bash
# Test that pg_basebackup can connect (will prompt for password)
pg_basebackup -h localhost -U alfresco -D /tmp/test_backup -Ft -z -P --wal-method=stream

# If successful, remove the test backup
rm -rf /tmp/test_backup
```

If you see errors, check:
- Database user has replication privileges: `ALTER USER alfresco REPLICATION;`
- `pg_hba.conf` allows replication connections
- Password is correct

### Troubleshooting WAL Configuration

**Script validation fails:**
The backup script will check these settings before running and provide specific error messages if something is wrong.

**WAL files not appearing in archive directory:**
```bash
# Check PostgreSQL logs for archive_command errors
sudo tail -f /var/log/postgresql/postgresql-14-main.log

# Common issues:
# - Wrong permissions on archive directory
# - Archive directory doesn't exist
# - Disk space full
```

**Replication permission denied:**
```bash
# Grant replication privilege to your backup user
sudo -u postgres psql -c "ALTER USER alfresco REPLICATION;"
```

## Backup Structure

```
BACKUP_DIR/
├── contentstore/
│   ├── daily-2025-01-15/
│   ├── daily-2025-01-16/
│   └── last -> daily-2025-01-16
├── postgres/
│   ├── base-2025-01-15/
│   └── base-2025-01-16/
├── pg_wal/
│   └── (WAL archive files)
└── backup-2025-01-16.log
```

## Email Alerts

Email alerts are sent **only on failures** and include:
- Which operation failed (PostgreSQL, Contentstore, WAL, Retention)
- Full error messages and stack traces
- Paths to failed backups
- Timestamps
- Log file location

No emails are sent for successful backups.

## Performance

The Python version has identical performance to the bash script because:
- Uses the same underlying tools (pg_basebackup, rsync)
- Python overhead is negligible (50ms startup vs hours of backup time)
- Same rsync hardlink strategy for space efficiency

## Troubleshooting

**Permission denied when installing packages in venv**:
If you created the venv with `sudo`, it's owned by root. Fix it:
```bash
# Remove the root-owned venv
cd /opt/alfresco-largecontentstore-backup
sudo rm -rf venv

# Ensure the directory is owned by your user
sudo chown -R $USER:$USER /opt/alfresco-largecontentstore-backup

# Recreate venv as regular user (no sudo)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Lock file error**:
- Another backup is running, or a previous backup crashed
- Remove `BACKUP_DIR/backup.lock` if you're sure no backup is running

**WAL configuration validation failed**:
- Check that PostgreSQL is configured for archiving
- Ensure `postgresql.conf` exists in one of the expected locations
- Verify `wal_level`, `archive_mode`, and `archive_command` are properly set
- See error message for specific missing/incorrect settings

**pg_basebackup not found**:
- Install PostgreSQL client tools: `sudo apt-get install -y postgresql-client`

**Email not sending**:
- Check SMTP credentials in .env
- For Gmail, use an app-specific password
- Check firewall allows SMTP port (587)

## Security

- `.env` file is gitignored and contains sensitive credentials
- Never commit `.env` to version control
- Set appropriate file permissions: `chmod 600 .env`

