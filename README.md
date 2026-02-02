# Alfresco Backup System

Production-grade backup and restore system for Alfresco deployments, designed to handle large contentstores (5TB+) with PostgreSQL database backups, contentstore snapshots, automated retention, and comprehensive restore capabilities.

NOTE: This is Vibecoded, but tested in Production.

## What Has Been Implemented

### Core Backup Features

**PostgreSQL Backup (`alfresco_backup/backup/postgres.py`)**
- SQL dump generation using `pg_dump` with embedded PostgreSQL binaries (version matching)
- Two-phase compression: creates uncompressed dump first to measure size, then compresses with `gzip`
- Automatic detection and use of Alfresco's embedded PostgreSQL tools to avoid version mismatches
- Size tracking (uncompressed and compressed) with compression ratio reporting
- S3 upload support for cloud storage (optional, requires rclone)
- Partial backup detection and reporting on failures
- Timeout handling with progress tracking

**Contentstore Backup (`alfresco_backup/backup/contentstore.py`)**
- Incremental snapshots using `rsync` with hardlink optimization (`--link-dest`)
- Parallel execution across top-level directories (year-based partitioning by default)
- Configurable parallelism (1-16 threads) for large contentstores
- Automatic discovery of top-level directories for parallel processing
- Disk space pre-check with warnings for low available space
- Failed backup cleanup (removes incomplete attempts < 12 hours old)
- S3 direct sync support using rclone (bypasses local storage entirely)
- Comprehensive progress tracking: files transferred, bytes transferred, duration
- Symlink management (`last` symlink points to most recent successful backup)
- Timeout configuration (default 24 hours, configurable)

**Retention Policy (`alfresco_backup/backup/retention.py`)**
- Time-based cleanup of PostgreSQL dumps and contentstore snapshots
- Configurable retention period (default 7 days)
- Timestamp parsing from directory/filename patterns
- Fallback to file modification time if timestamp parsing fails
- Error handling with detailed reporting of deletion failures

**Email Alerting (`alfresco_backup/backup/email_alert.py`)**
- Configurable alert modes: `both`, `failure_only`, `none`
- Detailed failure reports with partial progress information
- Success notifications (optional)
- Customer name customization for multi-tenant deployments
- SMTP authentication support (TLS)

**Process Locking (`alfresco_backup/utils/lock.py`)**
- File-based locking using `fcntl` to prevent concurrent executions
- Atomic lock acquisition with PID tracking
- Automatic cleanup on exit (context manager)
- Non-blocking lock attempts with clear error messages

### Restore Features

**Interactive Restore System (`alfresco_backup/restore/__main__.py`)**
- Full system restore (PostgreSQL + Contentstore)
- Component-level restore (PostgreSQL-only, Contentstore-only)
- Point-in-time recovery framework (PITR placeholder, requires WAL archiving)
- Backup validation before restore (size checks, file counts)
- Automatic backup of current data before restore
- Service management (start/stop Alfresco, Tomcat-only operations)
- PostgreSQL connection verification
- Progress bars using `tqdm` for long operations
- Comprehensive logging to file and console

**Restore Workflow**
1. Configuration loading (`.env` file or interactive prompts)
2. Backup selection (lists available backups with timestamps)
3. Validation (checks backup integrity)
4. Service coordination (starts PostgreSQL, stops Tomcat)
5. Data restoration (PostgreSQL via `gunzip | psql`, Contentstore via `rsync`)
6. Service restart (starts Tomcat, verifies services)

### Infrastructure Components

**Configuration Management (`alfresco_backup/utils/config.py`)**
- Environment variable loading via `python-dotenv`
- Required vs optional configuration validation
- S3 configuration detection (enables S3 mode if bucket specified)
- Path validation and existence checks
- Default value handling with sensible defaults
- Email configuration validation

**Subprocess Utilities (`alfresco_backup/utils/subprocess_utils.py`)**
- Consistent interface for long-running shell commands
- Timeout handling with progress tracking
- Safe filesystem path validation
- Error capture and reporting

**S3 Integration (`alfresco_backup/utils/s3_utils.py`)**
- rclone-based S3 sync for contentstore (direct from live to S3)
- File upload for PostgreSQL dumps
- Parallel transfer configuration
- Progress tracking and error handling
- Automatic rclone availability checking

**Setup Wizard (`setup.py`)**
- Interactive configuration wizard
- Auto-detection of database settings from `alfresco-global.properties`
- Virtual environment creation and dependency installation
- Directory creation with proper ownership
- Cron job configuration
- PostgreSQL WAL archiving configuration (optional)
- Restore-only mode (`--restore` flag)

**Wrapper Scripts (`backup.py`, `restore.py`)**
- Automatic virtual environment detection
- Backward compatibility with existing cron jobs
- Clear error messages for missing dependencies
- Path resolution for venv imports

## How It Works Internally

### Backup Execution Flow

```
1. Configuration Loading
   └─> BackupConfig loads .env file
       ├─> Validates required variables
       ├─> Detects S3 mode (if S3_BUCKET set)
       └─> Sets up email configuration

2. Logging Setup
   └─> Creates daily log file (backup-YYYY-MM-DD.log)
       └─> Dual handlers: file + console

3. Lock Acquisition
   └─> FileLock context manager
       ├─> Creates lockfile atomically
       ├─> Uses fcntl.LOCK_EX | LOCK_NB
       └─> Writes PID for debugging

4. PostgreSQL Backup
   └─> backup_postgres(config)
       ├─> Detects embedded pg_dump (alf_base_dir/postgresql/bin/pg_dump)
       ├─> Creates temporary uncompressed dump
       ├─> Measures uncompressed size
       ├─> Compresses with gzip
       ├─> Measures compressed size
       ├─> Uploads to S3 if configured
       └─> Returns result dict with success, path, sizes, duration

5. Contentstore Backup
   └─> backup_contentstore(config)
       ├─> Discovers top-level directories (year-based typically)
       ├─> Decides parallel vs single-threaded
       ├─> If parallel:
       │   ├─> Creates ThreadPoolExecutor (configurable threads)
       │   ├─> Submits rsync tasks per directory
       │   ├─> Collects results as they complete
       │   └─> Aggregates statistics
       ├─> If single-threaded:
       │   └─> Single rsync with --link-dest optimization
       ├─> Updates 'last' symlink
       └─> Returns result dict with success, path, sizes, file counts

6. Retention Policy
   └─> apply_retention(config)
       ├─> Scans contentstore/ and postgres/ directories
       ├─> Parses timestamps from directory/filename patterns
       ├─> Compares against retention_days threshold
       └─> Deletes old backups

7. Email Alerting
   └─> If any failure:
       └─> send_failure_alert(backup_results, config)
           ├─> Builds detailed failure report
           ├─> Includes partial progress if available
           └─> Sends via SMTP
   └─> If all success and mode == 'both':
       └─> send_success_alert(backup_results, config)
```

### Contentstore Hardlink Strategy

The contentstore backup uses rsync's `--link-dest` option to create incremental backups efficiently:

```
Backup 1 (Day 1):
  contentstore-2025-01-01_02-00-00/
    ├── 2020/ (actual files)
    ├── 2021/ (actual files)
    └── 2022/ (actual files)
  Total size: 5TB

Backup 2 (Day 2):
  contentstore-2025-01-02_02-00-00/
    ├── 2020/ (hardlinks to Backup 1)
    ├── 2021/ (hardlinks to Backup 1)
    └── 2022/ (hardlinks + new files)
  Total size: 5TB (but only ~100GB additional disk usage)
  
The 'last' symlink points to the most recent backup, used as --link-dest for the next backup.
```

**Key Benefits:**
- Only changed/new files consume additional disk space
- Each backup appears as a complete snapshot (can be used independently)
- Hardlinks share the same inode, so deletion is safe (unlink only removes the link)

### Parallel Execution Strategy

For large contentstores, the system can process multiple top-level directories in parallel:

```
Contentstore structure:
  contentstore/
    ├── 2020/ (1TB)
    ├── 2021/ (1.2TB)
    ├── 2022/ (1.5TB)
    └── 2023/ (1.3TB)

With CONTENTSTORE_PARALLEL_THREADS=4:
  Thread 1: rsync 2020/ → backup/2020/
  Thread 2: rsync 2021/ → backup/2021/
  Thread 3: rsync 2022/ → backup/2022/
  Thread 4: rsync 2023/ → backup/2023/
  
All run concurrently, completion time ≈ max(individual durations)
```

**Implementation Details:**
- Uses `ThreadPoolExecutor` with configurable worker count
- Each thread runs independent rsync process
- Results aggregated with error collection
- Failed chunks don't block successful ones (partial success possible)

### S3 Backup Mode

When `S3_BUCKET` is configured, backups bypass local storage:

```
PostgreSQL Backup:
  1. Create compressed dump in temp directory
  2. Upload to s3://bucket/alfresco-backups/postgres/
  3. Clean up temp file
  4. Result path points to S3 location

Contentstore Backup:
  1. Sync directly from live contentstore to S3
  2. Uses rclone sync (not rsync)
  3. Parallel transfers configured via CONTENTSTORE_PARALLEL_THREADS
  4. No local snapshot created
```

**S3 Requirements:**
- rclone must be installed
- AWS credentials (access key ID, secret access key)
- S3 bucket with appropriate permissions
- S3 versioning recommended for incremental backups

### Restore Execution Flow

```
1. Configuration Loading
   └─> RestoreConfig loads .env or prompts interactively

2. Backup Selection
   └─> Lists available backups (sorted by timestamp, newest first)
       ├─> PostgreSQL backups: postgres-YYYY-MM-DD_HH-MM-SS.sql.gz
       └─> Contentstore backups: contentstore-YYYY-MM-DD_HH-MM-SS/

3. Validation
   └─> Validates backup exists and has reasonable size
       ├─> PostgreSQL: file size check (> 0.1 MB)
       └─> Contentstore: file count check (> 0 files)

4. Service Coordination
   └─> start_alfresco_full()
       ├─> Starts all services (including PostgreSQL)
       └─> Waits 2 minutes for initialization
   └─> stop_tomcat_only()
       └─> Stops Tomcat, leaves PostgreSQL running
   └─> verify_postgresql_running()
       └─> Tests connection with psql

5. Current Data Backup
   └─> backup_current_data()
       ├─> Moves postgresql data directory to .backup.TIMESTAMP
       └─> Moves contentstore to .backup.TIMESTAMP

6. PostgreSQL Restore
   └─> restore_postgres(timestamp)
       ├─> gunzip -c backup.sql.gz | psql
       ├─> Progress bar via tqdm
       └─> Error handling for partial restores

7. Contentstore Restore
   └─> restore_contentstore(timestamp)
       ├─> rsync -av --delete source/ destination/
       ├─> Progress tracking
       └─> Sets ownership to alfresco user

8. Service Restart
   └─> start_tomcat_only()
       └─> Starts Tomcat (PostgreSQL already running)
```

## How to Use It

### Initial Setup

**Full Backup System Setup:**
```bash
git clone <repository-url>
cd alfresco-largecontentstore-backup
sudo python3 setup.py
```

The setup wizard will:
1. Check prerequisites (Python 3, rsync, pg_dump)
2. Create `.env` file with configuration
3. Create backup directories
4. Create Python virtual environment
5. Install dependencies
6. Configure cron job (optional)
7. Verify installation

**Restore-Only Setup:**
```bash
python3 setup.py --restore
```

This creates venv and installs dependencies only (no backup configuration needed).

### Configuration

All configuration is stored in `.env` file. Key settings:

**Required (unless S3 mode):**
- `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` - PostgreSQL connection
- `ALF_BASE_DIR` - Path to Alfresco installation
- `BACKUP_DIR` - Local backup destination (not needed for S3)
- `RETENTION_DAYS` - How long to keep backups (default: 7)

**Optional:**
- `CONTENTSTORE_TIMEOUT_HOURS` - Timeout for contentstore backup (default: 24)
- `CONTENTSTORE_PARALLEL_THREADS` - Parallel threads for large backups (default: 4)
- `S3_BUCKET`, `S3_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` - S3 mode
- `EMAIL_ALERT_MODE` - `both`, `failure_only`, or `none`
- `SMTP_*` - Email alert configuration

See `env.example` for complete configuration template.

### Running Backups

**Manual Execution:**
```bash
# Scripts auto-detect venv
python backup.py

# Or explicitly use venv
source venv/bin/activate
python backup.py

# Or use venv Python directly
venv/bin/python backup.py
```

**Automated Execution:**
Cron job configured by setup wizard (default: daily at 2 AM):
```bash
0 2 * * * cd /path/to/project && venv/bin/python backup.py >> /var/log/alfresco-backup/cron-$(date +\%Y-\%m-\%d).log 2>&1
```

**Monitoring:**
- Logs written to `BACKUP_DIR/backup-YYYY-MM-DD.log`
- Email alerts sent on failures (if configured)
- Lock file prevents concurrent executions

### Running Restores

**Interactive Restore:**
```bash
python restore.py
```

The restore script will:
1. Load configuration from `.env` (or prompt if missing)
2. List available backups
3. Prompt for restore mode (full, PostgreSQL-only, etc.)
4. Validate selected backups
5. Execute restore with progress feedback
6. Log all operations to `restore-YYYYMMDD-HHMMSS.log`

**Restore Modes:**
- **Full System Restore**: Restores both PostgreSQL and contentstore
- **PostgreSQL Only**: Restores database only (useful for schema changes)
- **Contentstore Only**: Not fully implemented (placeholder)

### Troubleshooting

**Backup Failures:**
1. Check log file: `BACKUP_DIR/backup-YYYY-MM-DD.log`
2. Verify disk space: `df -h BACKUP_DIR`
3. Check lock file: `BACKUP_DIR/backup.lock` (remove if stale)
4. Verify PostgreSQL connection: `psql -h $PGHOST -p $PGPORT -U $PGUSER -d $PGDATABASE`

**Restore Failures:**
1. Check restore log: `restore-YYYYMMDD-HHMMSS.log`
2. Verify backup integrity: Check file sizes and counts
3. Ensure PostgreSQL is running: `systemctl status postgresql` (or Alfresco services)
4. Verify file permissions: Contentstore must be writable by Alfresco user

**Common Issues:**
- **Lock file exists**: Another backup is running, or previous backup crashed. Remove lock file if process is not running.
- **Low disk space**: Increase retention period or clean up old backups manually.
- **Timeout errors**: Increase `CONTENTSTORE_TIMEOUT_HOURS` for very large contentstores.
- **S3 upload failures**: Verify rclone is installed and credentials are correct.

## Project Structure

```
alfresco-largecontentstore-backup/
├── alfresco_backup/           # Main Python package
│   ├── backup/                # Backup modules
│   │   ├── __main__.py       # Backup orchestrator
│   │   ├── postgres.py        # PostgreSQL backup logic
│   │   ├── contentstore.py    # Contentstore backup logic
│   │   ├── retention.py       # Retention policy enforcement
│   │   ├── email_alert.py     # Email notification system
│   │   └── wal.py             # WAL archive utilities (optional)
│   ├── restore/               # Restore modules
│   │   └── __main__.py        # Interactive restore orchestrator
│   └── utils/                 # Shared utilities
│       ├── config.py          # Configuration loader
│       ├── lock.py            # Process locking
│       ├── subprocess_utils.py # Subprocess execution helpers
│       └── s3_utils.py         # S3 integration via rclone
├── backup.py                  # Wrapper script (backward compatibility)
├── restore.py                 # Wrapper script (backward compatibility)
├── setup.py                   # Interactive setup wizard
├── cleanup_backups.py         # Manual cleanup tool
├── requirements.txt           # Python dependencies
├── env.example               # Configuration template
└── docs/                      # Documentation
    ├── architecture.md        # System architecture
    ├── setup/                 # Setup guides
    └── operations/            # Operational guides
```

## Extension Points for Developers

**Adding New Backup Types:**
1. Create module in `alfresco_backup/backup/`
2. Implement function returning dict with `success`, `path`, `error`, `duration` keys
3. Add call in `alfresco_backup/backup/__main__.py`
4. Update email alerting to include new backup type

**Customizing Retention Logic:**
- Modify `alfresco_backup/backup/retention.py`
- Add custom filters or retention rules
- Extend timestamp parsing if using different naming patterns

**Adding Storage Backends:**
- Create new module in `alfresco_backup/utils/` (similar to `s3_utils.py`)
- Implement sync/upload functions
- Add configuration detection in `BackupConfig`
- Update backup modules to use new backend

**Enhancing Restore:**
- Extend `AlfrescoRestore` class in `alfresco_backup/restore/__main__.py`
- Add new restore modes or validation steps
- Implement PITR if WAL archiving is enabled

## Documentation Map

- [Setup & Installation](docs/setup/installation.md) - Detailed setup instructions
- [Backup Operations Guide](docs/operations/backup-guide.md) - Backup procedures and best practices
- [Restore Runbook](docs/operations/restore-runbook.md) - Step-by-step restore procedures
- [Restore Quick Reference](docs/operations/restore-cheatsheet.md) - Quick restore commands
- [Disk Space Management](docs/operations/disk-space-management.md) - Managing disk space for large backups
- [Maintenance & Security Guide](docs/operations/maintenance-and-security.md) - Security and maintenance procedures
- [Architecture Overview](docs/architecture.md) - System architecture and design decisions

## Contributing

Issues and improvements are welcome. When contributing:

1. Maintain modularity: Keep backup, restore, and utility modules separate
2. Preserve backward compatibility: Wrapper scripts (`backup.py`, `restore.py`) must continue to work
3. Follow existing patterns: Use result dicts, context managers for resources, comprehensive logging
4. Update documentation: Keep README and docs/ in sync with changes
5. Test with large contentstores: System is designed for 5TB+ deployments

## License

Released under the MIT License. See [`LICENSE`](LICENSE) for details.

