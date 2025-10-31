# Backup Operations Guide

This document covers day-to-day backup execution, scheduling, retention, and monitoring for the Alfresco Backup System.

## Running Backups Manually

Activate the project virtual environment (if created) and run the wrapper script:

```bash
cd /opt/alfresco-largecontentstore-backup
source venv/bin/activate
python backup.py            # Uses .env in the current directory
python backup.py /path/to/custom.env  # Optional override
```

During execution the orchestrator:

1. Loads configuration and creates the daily log file in `BACKUP_DIR`.
2. Validates PostgreSQL WAL settings and acquires the process lock.
3. Runs PostgreSQL base backup, contentstore snapshot, WAL archive inspection, and retention policy in sequence.
4. Sends an email alert if any step fails.

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

Retention is applied automatically by `retention.py` at the end of each run. Items older than `RETENTION_DAYS` are deleted from:

- `BACKUP_DIR/postgres/base-*`
- `BACKUP_DIR/contentstore/contentstore-*`
- `BACKUP_DIR/pg_wal/`

Timestamps embedded in directory names are used when available; otherwise the filesystem modification time is used as a fallback.

## What Gets Backed Up

```
BACKUP_DIR/
├── postgres/        # Timestamped base backups produced by pg_basebackup
├── contentstore/    # rsync snapshots with hardlink optimisation
└── pg_wal/          # WAL archive for PITR
```

Each run creates:

- `postgres/base-YYYY-MM-DD_HH-MM-SS/base.tar.gz`
- `contentstore/contentstore-YYYY-MM-DD_HH-MM-SS` with optional `last` symlink
- Updated WAL archive files in `pg_wal`

## Email Alerts

When any backup step fails the system sends a detailed email that summarises each component’s status, includes timestamps, and references the log file path. SMTP credentials and recipients are configured via `.env`.

## Performance Notes

The Python implementation delegates heavy lifting to `pg_basebackup` and `rsync`; Python overhead is negligible compared to transfer time. Hardlink-based contentstore snapshots significantly reduce disk utilisation for daily jobs.

## Operational Checklist

- Confirm the cron job runs as the Alfresco user.
- Monitor free disk space on the backup volume (`df -h BACKUP_DIR`).
- Review failure alerts promptly and re-run backups after addressing root causes.
- Periodically test restores following `restore-runbook.md` to validate backup integrity.
