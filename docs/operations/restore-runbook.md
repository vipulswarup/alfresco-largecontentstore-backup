# Restore Runbook

This runbook provides detailed instructions for restoring Alfresco from backups created by this system. Pair it with `restore-cheatsheet.md` for quick commands.

## Table of Contents

1. [Before You Begin](#before-you-begin)
2. [PostgreSQL Restore](#postgresql-restore)
3. [Contentstore Restore](#contentstore-restore)
4. [Full System Restore](#full-system-restore)
5. [Point-in-Time Recovery (PITR)](#point-in-time-recovery-pitr)
6. [Verification](#verification)
7. [Troubleshooting](#troubleshooting)
8. [Testing Restores](#testing-restores)

---

## Before You Begin

### Prerequisites

- Root or sudo access to the Alfresco server
- Alfresco services stopped during restore operations
- Sufficient disk space for temporary copies
- Access to backup files under `BACKUP_DIR`

### Safety Checklist

1. Test the procedure on non-production where possible.
2. Take a fresh snapshot or backup of the current system.
3. Document the current configuration (database users, paths, versions).
4. Validate the integrity of the target backup before starting.
5. Plan for downtime appropriate to the size of your repository.

### Backup Integrity Check

```bash
BACKUP_DIR=/mnt/backups/alfresco
RESTORE_DATE=2025-10-21_14-31-23  # replace with desired timestamp

ls -lh $BACKUP_DIR/postgres/postgres-$RESTORE_DATE.sql.gz
ls -lh $BACKUP_DIR/contentstore/contentstore-$RESTORE_DATE/
```

Confirm that the SQL dump file exists and the contentstore directory contains data before proceeding.

---

## PostgreSQL Restore

### SQL Dump Restore

1. **Stop Alfresco**

   ```bash
   cd /opt/eisenvault_installations/alfresco-home
   ./alfresco.sh stop
   pgrep -f "java.*alfresco" || echo "Alfresco stopped"
   ```

2. **Load Database Configuration**

   The restore process reads connection details from `.env` file. Ensure the file exists and contains:
   
   ```bash
   PGHOST=localhost
   PGPORT=5432
   PGUSER=alfresco
   PGPASSWORD=your_password
   PGDATABASE=postgres
   ```

3. **Restore SQL Dump**

   ```bash
   BACKUP_DIR=/mnt/backups/alfresco
   RESTORE_DATE=2025-10-21_14-31-23
   ALF_BASE_DIR=/opt/eisenvault_installations/alfresco-home
   
   # Use the automated restore script (recommended)
   cd /path/to/alfresco-largecontentstore-backup
   # The restore script automatically detects and uses the local venv if it exists
   # Or activate manually: source venv/bin/activate
   python restore.py
   # Select option 3 (PostgreSQL only) and follow prompts
   
   # Or restore manually:
   gunzip -c $BACKUP_DIR/postgres/postgres-$RESTORE_DATE.sql.gz | \
     psql -h localhost -U alfresco -d postgres
   ```

4. **Verify Connectivity**

   ```bash
   psql -h localhost -U alfresco -d alfresco -c "SELECT COUNT(*) FROM alf_node;"
   ```

---

## Contentstore Restore

1. **Stop Alfresco**

   ```bash
   cd /opt/eisenvault_installations/alfresco-home
   ./alfresco.sh stop
   pgrep -f "java.*alfresco" || echo "Alfresco stopped"
   ```

2. **Backup Current Contentstore**

   ```bash
   ALF_BASE_DIR=/opt/eisenvault_installations/alfresco-home
   CONTENTSTORE_DIR=$ALF_BASE_DIR/alf_data/contentstore
   sudo mv $CONTENTSTORE_DIR ${CONTENTSTORE_DIR}.backup.$(date +%Y%m%d-%H%M%S)
   ```

3. **Restore Snapshot**

   ```bash
   BACKUP_DIR=/mnt/backups/alfresco
   RESTORE_DATE=2025-10-21_14-31-23
   ALF_BASE_DIR=/opt/eisenvault_installations/alfresco-home
   CONTENTSTORE_DIR=$ALF_BASE_DIR/alf_data/contentstore

   sudo mkdir -p $CONTENTSTORE_DIR
   sudo rsync -av --delete \
        $BACKUP_DIR/contentstore/contentstore-$RESTORE_DATE/ \
        $CONTENTSTORE_DIR/
   sudo chown -R evadm:evadm $CONTENTSTORE_DIR
   ```

4. **Verify File Count**

   ```bash
   find $CONTENTSTORE_DIR -type f | wc -l
   ```

---

## Full System Restore

Use matching timestamps for PostgreSQL and contentstore backups to avoid data mismatch.

```bash
BACKUP_DIR=/mnt/backups/alfresco
ls -1 $BACKUP_DIR/postgres/
ls -1 $BACKUP_DIR/contentstore/
```

1. Stop Alfresco.
2. Backup existing `alf_data/postgresql/data` and `alf_data/contentstore` directories (automatically done by restore script).
3. Restore PostgreSQL from SQL dump (see PostgreSQL Restore section).
4. Restore contentstore (see Contentstore Restore section).
5. Start Alfresco and monitor `tomcat/logs/catalina.out`.

The automated restore script (`restore.py`) handles all these steps interactively. Select option 1 (Full system restore) when prompted.

---

## Point-in-Time Recovery (PITR)

**Note:** Point-in-time recovery is not supported with SQL dump backups. SQL dumps provide snapshot recovery only, meaning you can restore to the exact state captured at backup time, but not to an arbitrary point between backups.

To restore to a specific time:
1. Identify the backup closest to your desired recovery point.
2. Use that backup for restoration (see Full System Restore above).
3. If more recent data is needed, consider implementing transaction log backups or switching to a WAL-based backup strategy.

For snapshot recovery, select the backup timestamp that best matches your recovery point objective.

---

## Verification

After any restore, validate each layer:

1. **Database Health**

   ```bash
   psql -h localhost -U alfresco -d alfresco <<'SQL'
   SELECT pg_size_pretty(pg_database_size('alfresco'));
   SELECT COUNT(*) FROM alf_node;
   SELECT COUNT(*) FROM alf_content_data;
   SQL
   ```

2. **Contentstore Integrity**

   ```bash
   find $ALF_BASE_DIR/alf_data/contentstore -type f | wc -l
   ls -la $ALF_BASE_DIR/alf_data/contentstore | head
   ```

3. **Alfresco Application**

   ```bash
   tail -100 $ALF_BASE_DIR/tomcat/logs/catalina.out
   ```

4. **Functional Checks**

   - Log into Alfresco Share.
   - Browse documents and verify previews.
   - Run searches and confirm results.

---

## Troubleshooting

### PostgreSQL Fails to Start

```bash
sudo chown -R evadm:evadm $ALF_BASE_DIR/alf_data/postgresql/data
sudo chmod 700 $ALF_BASE_DIR/alf_data/postgresql/data
sudo rm -f $ALF_BASE_DIR/alf_data/postgresql/data/postmaster.pid
tail -100 $ALF_BASE_DIR/alf_data/postgresql/postgresql.log
```

### SQL Dump File Corrupted

```bash
# Verify file integrity
gunzip -t $BACKUP_DIR/postgres/postgres-$RESTORE_DATE.sql.gz

# If corrupted, try a different backup
ls -lh $BACKUP_DIR/postgres/
```

### Contentstore Looks Empty

```bash
ls -la $ALF_BASE_DIR/alf_data/contentstore/
sudo chown -R evadm:evadm $ALF_BASE_DIR/alf_data/contentstore
```

### Alfresco Starts with Errors

- Confirm PostgreSQL and contentstore timestamps match.
- Clear Tomcat caches:

  ```bash
  rm -rf $ALF_BASE_DIR/tomcat/temp/*
  rm -rf $ALF_BASE_DIR/tomcat/work/*
  ```

- Review configuration (`alfresco-global.properties`).

### Restore Taking Too Long

- Check disk I/O with `iostat -x 5`.
- Ensure adequate free space (`df -h`).
- For PostgreSQL, extract to faster storage then move into place.

### Database Version Mismatch

SQL dumps are generally portable across PostgreSQL versions, but some features may differ. If you encounter version-specific errors:

```bash
# Check PostgreSQL version
psql -h localhost -U alfresco -c "SELECT version();"

# Review dump file for version-specific syntax
gunzip -c $BACKUP_DIR/postgres/postgres-$RESTORE_DATE.sql.gz | head -20
```

If versions differ significantly, consider using `pg_dump` with version-specific options or restoring to a matching PostgreSQL version.

---

## Testing Restores

Run restore tests regularly to ensure procedures remain valid.

```bash
psql -h localhost -U alfresco -d alfresco -c "SELECT COUNT(*) FROM alf_node;" > /tmp/pre_restore_state.txt
# Perform restore on a staging environment
# Compare post-restore metrics and document lessons learned
```

### Suggested Schedule

- **Monthly**: Spot-check backups, review logs, verify cron output.
- **Quarterly**: Full restore drill on non-production.
- **Annually**: Revisit disaster recovery plans and off-site replication strategy.

Maintain a contact list for emergency escalations (DBA, system admin, Alfresco owner, on-call support) and store it alongside this runbook.
