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

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Create your `.env` file from the example:
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

3. Make the backup script executable:
```bash
chmod +x backup.py
```

## Usage

Run the backup:
```bash
python backup.py
```

Or specify a custom env file location:
```bash
python backup.py /path/to/custom.env
```

## Scheduling with Cron

Add to crontab for daily backups at 2 AM:
```bash
0 2 * * * cd /path/to/peso-backup-system && python backup.py >> /var/log/alfresco-backup-cron.log 2>&1
```

## What Gets Backed Up

1. **PostgreSQL Database**: Full base backup using pg_basebackup in compressed tar format
2. **Contentstore**: All files in `ALF_BASE_DIR/contentstore` using rsync with hardlinks
3. **WAL Files**: Monitored in `BACKUP_DIR/pg_wal` for PITR capability

## PostgreSQL WAL Configuration Requirements

Before backups can run, the script validates that PostgreSQL is properly configured for WAL archiving. It checks for `postgresql.conf` in these locations:
1. `ALF_BASE_DIR/alf_data/postgresql/postgresql.conf`
2. `ALF_BASE_DIR/postgresql/postgresql.conf`

**Required settings:**
- `wal_level = replica` or `logical` (NOT minimal)
- `archive_mode = on`
- `archive_command` must be set to copy WAL files

If any of these settings are missing or incorrect, the backup will fail immediately with a clear error message indicating what needs to be fixed.

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

**Lock file error**:
- Another backup is running, or a previous backup crashed
- Remove `BACKUP_DIR/backup.lock` if you're sure no backup is running

**WAL configuration validation failed**:
- Check that PostgreSQL is configured for archiving
- Ensure `postgresql.conf` exists in one of the expected locations
- Verify `wal_level`, `archive_mode`, and `archive_command` are properly set
- See error message for specific missing/incorrect settings

**pg_basebackup not found**:
- Install PostgreSQL client tools: `apt-get install postgresql-client`

**Email not sending**:
- Check SMTP credentials in .env
- For Gmail, use an app-specific password
- Check firewall allows SMTP port (587)

## Migration from Bash Script

The original `alfresco-backup.sh` is kept for reference. To migrate:

1. Run one test backup with Python version to a different directory
2. Verify backup integrity
3. Update cron job to use Python version
4. Monitor for one week
5. Remove bash script once confident

## Security

- `.env` file is gitignored and contains sensitive credentials
- Never commit `.env` to version control
- Set appropriate file permissions: `chmod 600 .env`

