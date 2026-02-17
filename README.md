# Alfresco Backup System

Production-grade backup and restore system for Alfresco deployments, designed to handle large contentstores (5TB+) with PostgreSQL database backups, contentstore snapshots, automated retention, and comprehensive restore capabilities.

## Quick Start

### Prerequisites

**Required system packages:**
```bash
# On Debian/Ubuntu:
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv postgresql-client rsync rclone

# On RHEL/CentOS:
sudo yum install python3 python3-pip postgresql rsync rclone
```

**Note:** The setup wizard will check for these tools and provide installation instructions if any are missing.

### Installation

**For Backup System (full setup):**
```bash
git clone <repository-url>
cd alfresco-largecontentstore-backup
sudo python3 setup.py
```

The setup wizard will guide you through configuration and create a virtual environment.

**For Restore Only (no backup configuration needed):**
```bash
git clone <repository-url>
cd alfresco-largecontentstore-backup
python3 setup.py --restore
```

**Note:** If you get an error about `python3-venv` not being available, install it first:
```bash
sudo apt install python3-venv
# Or for specific Python version:
sudo apt install python3.12-venv
```

Then run `python3 setup.py --restore` again.

### Running Backups

**Manual:**
```bash
python3 backup.py
```

**Automated (via cron):**
Setup wizard configures daily backups at 2 AM. Check cron with `crontab -l`.

### Running Restores

**First-time setup (if virtual environment doesn't exist):**
```bash
python3 setup.py --restore
```

This creates the virtual environment and installs dependencies without requiring backup configuration.

**Then run restore:**
```bash
python3 restore.py
```

Select restore mode and follow prompts. The restore script will prompt you to clear Solr4 indexes after restore (recommended). Alfresco will rebuild indexes automatically on next startup.

## Configuration

Configuration is stored in `.env` file. Key settings:

**Required:**
- `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` - PostgreSQL connection
- `ALF_BASE_DIR` - Path to Alfresco installation
- `BACKUP_DIR` - Local backup destination (not needed for S3 mode)
- `RETENTION_DAYS` - How long to keep backups (default: 7)

**Optional:**
- `S3_BUCKET`, `S3_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` - S3 mode
- `CONTENTSTORE_PARALLEL_THREADS` - Parallel threads for large backups (default: 4)
- `EMAIL_ALERT_MODE` - `both`, `failure_only`, or `none`
- `SMTP_*` - Email alert configuration

See `env.example` for complete template.

## Restore Process

The restore system supports multiple modes:

1. **Full System Restore** - Restores PostgreSQL and contentstore
2. **Point-in-Time Recovery (PITR)** - Restores to specific timestamp using S3 versioning
3. **PostgreSQL Only** - Database restore only
4. **Contentstore Only** - Contentstore restore only

### Restore Steps

1. Start Alfresco services (PostgreSQL must be running)
2. Stop Tomcat (PostgreSQL remains running)
3. Backup current data (automatic)
4. Restore PostgreSQL from SQL dump
5. Restore contentstore (local rsync or S3 versioning)
6. **Clear Solr4 indexes** (prompted by restore script, recommended)
7. Start Tomcat
8. Verify services are running

### Clearing Solr4 Indexes After Restore

After restore, Solr4 indexes must be cleared to avoid search errors. The restore script will prompt you to clear indexes automatically. If you skip this step, clear them manually:

**For embedded Solr4:**
```bash
ALF_BASE_DIR=/opt/eisenvault_installations/eisenvault-dms
rm -rf $ALF_BASE_DIR/alf_data/solr4/workspace/SpacesStore/index
rm -rf $ALF_BASE_DIR/alf_data/solr4/archive/SpacesStore/index
```

**For external Solr:**
```bash
rm -rf $ALF_BASE_DIR/alf_data/solr4/index
```

**Note:** The restore script will prompt you to clear indexes. Alfresco will rebuild indexes automatically on next startup.

## Features

### Backup Features

- **PostgreSQL Backup**: SQL dumps using embedded PostgreSQL binaries (version matching)
- **Contentstore Backup**: Incremental snapshots using rsync with hardlink optimization
- **S3 Support**: Direct S3 sync for contentstore, upload for PostgreSQL dumps
- **Parallel Processing**: Configurable parallelism for large contentstores (5TB+)
- **Retention Policy**: Automatic cleanup of old backups
- **Email Alerts**: Configurable success/failure notifications

### Restore Features

- **Interactive Restore**: Step-by-step restore with backup selection
- **Point-in-Time Recovery**: S3 versioning support for contentstore PITR
- **Service Management**: Automatic start/stop of Alfresco services
- **Progress Tracking**: Real-time progress bars for long operations
- **Comprehensive Logging**: Detailed logs for troubleshooting

## How It Works

### Backup Strategy

**PostgreSQL:** Creates compressed SQL dumps using `pg_dump`. For S3 mode, uploads directly to S3.

**Contentstore:** Uses `rsync` with `--link-dest` for incremental backups. Only changed files consume additional disk space. For S3 mode, syncs directly from live contentstore to S3 using `rclone`.

**Parallel Execution:** Large contentstores are processed in parallel across top-level directories (typically year-based), significantly reducing backup time.

### Restore Strategy

1. **Service Coordination**: Starts PostgreSQL, stops Tomcat for safe restore
2. **Data Backup**: Automatically backs up current data before restore
3. **Database Restore**: Restores SQL dump via `gunzip | psql`
4. **Contentstore Restore**: Restores via `rsync` (local) or `rclone --s3-version-at` (S3 PITR)
5. **Index Clearing**: Solr4 indexes must be cleared manually after restore
6. **Service Restart**: Starts Tomcat and verifies services

## Troubleshooting

**Backup Failures:**
- Check log file: `BACKUP_DIR/backup-YYYY-MM-DD.log`
- Verify disk space: `df -h BACKUP_DIR`
- Check lock file: Remove `BACKUP_DIR/backup.lock` if stale

**Restore Failures:**
- Check restore log: `restore-YYYYMMDD-HHMMSS.log`
- Verify PostgreSQL is running: `psql -h $PGHOST -p $PGPORT -U $PGUSER -d $PGDATABASE`
- Clear Solr4 indexes if search errors occur after restore

**Common Issues:**
- **Lock file exists**: Another backup is running, or previous backup crashed
- **Low disk space**: Increase retention period or clean up old backups
- **S3 upload failures**: Verify rclone is installed and credentials are correct
- **Solr errors after restore**: Clear Solr4 indexes (see Restore Process section)

## Project Structure

```
alfresco-largecontentstore-backup/
├── alfresco_backup/           # Main Python package
│   ├── backup/                # Backup modules
│   ├── restore/               # Restore modules
│   └── utils/                 # Shared utilities
├── backup.py                  # Backup wrapper script
├── restore.py                 # Restore wrapper script
├── setup.py                   # Interactive setup wizard
├── requirements.txt           # Python dependencies
└── docs/                      # Detailed documentation
```

## Documentation

- [Setup & Installation](docs/setup/installation.md) - Detailed setup instructions
- [Backup Operations Guide](docs/operations/backup-guide.md) - Backup procedures
- [Restore Runbook](docs/operations/restore-runbook.md) - Step-by-step restore procedures
- [Architecture Overview](docs/architecture.md) - System architecture

## License

Released under the MIT License. See [`LICENSE`](LICENSE) for details.
