# Backup Operations Guide

This document covers day-to-day backup execution, scheduling, retention, and monitoring for the Alfresco Backup System.

## Running Backups Manually

Run the backup script. The script automatically detects and uses the local virtual environment if it exists:

```bash
cd /opt/alfresco-largecontentstore-backup
# Automatic venv detection (recommended)
python backup.py            # Uses .env in the current directory
python backup.py /path/to/custom.env  # Optional override

# Or activate the venv manually (also works)
source venv/bin/activate
python backup.py
```

During execution the orchestrator:

1. Loads configuration and creates the daily log file in `BACKUP_DIR`.
2. Acquires the process lock to prevent concurrent executions.
3. Runs PostgreSQL SQL dump, contentstore snapshot, and retention policy in sequence.
4. Sends email alerts based on `EMAIL_ALERT_MODE` configuration (see Email Alerts section).

## Scheduling with Cron

Run the cron job as the same Linux user that owns Alfresco to avoid permission issues. Two common patterns are shown below.

### Virtual Environment Install

```bash
0 2 * * * cd /opt/alfresco-largecontentstore-backup && \
  /opt/alfresco-largecontentstore-backup/venv/bin/python \
  /opt/alfresco-largecontentstore-backup/backup.py \
  >> /var/log/alfresco-backup/cron-$(date +\%Y-\%m-\%d).log 2>&1
```

### System Python

```bash
0 2 * * * cd /opt/alfresco-largecontentstore-backup && \
  python3 backup.py \
  >> /var/log/alfresco-backup/cron-$(date +\%Y-\%m-\%d).log 2>&1
```

Create the log directory first:

```bash
sudo mkdir -p /var/log/alfresco-backup
sudo chown $USER:$USER /var/log/alfresco-backup
sudo chmod 755 /var/log/alfresco-backup
```

## Logs and Monitoring

- Daily run log: `BACKUP_DIR/backup-YYYY-MM-DD.log`
- Cron log: `/var/log/alfresco-backup/cron-YYYY-MM-DD.log`
- Email notifications: sent on failure only (see below)

Check both logs after initial deployment and periodically review them to confirm backups finish successfully.

## Retention Policy

Retention is applied automatically by `retention.py` at the end of each run. Items older than `RETENTION_DAYS` (default 7 days) are deleted from:

- `BACKUP_DIR/postgres/postgres-*.sql.gz`
- `BACKUP_DIR/contentstore/contentstore-*`

Timestamps embedded in filenames are used when available; otherwise the filesystem modification time is used as a fallback.

## What Gets Backed Up

```
BACKUP_DIR/
├── postgres/        # Compressed SQL dump files created by pg_dump
└── contentstore/    # rsync snapshots with hardlink optimisation
```

Each run creates:

- `postgres/postgres-YYYY-MM-DD_HH-MM-SS.sql.gz` (compressed SQL dump)
- `contentstore/contentstore-YYYY-MM-DD_HH-MM-SS/` with optional `last` symlink

## Email Alerts

Email alerts are controlled by the `EMAIL_ALERT_MODE` setting in `.env`:

- **`failure_only`** (default): Send emails only when backups fail
- **`both`**: Send emails on both successful and failed backups
- **`none`**: Disable all email alerts

When enabled, emails include detailed information about each component's status, timestamps, size information, and log file path. SMTP credentials and recipients are configured via `.env`.

## Performance Notes

The Python implementation delegates heavy lifting to `pg_dump` and `rsync`; Python overhead is negligible compared to transfer time. Hardlink-based contentstore snapshots significantly reduce disk utilisation for daily jobs. SQL dumps are compressed with gzip to minimise storage requirements.

## Operational Checklist

- Confirm the cron job runs as the Alfresco user.
- Monitor free disk space on the backup volume (`df -h BACKUP_DIR`).
- Review failure alerts promptly and re-run backups after addressing root causes.
- Periodically test restores following `restore-runbook.md` to validate backup integrity.
