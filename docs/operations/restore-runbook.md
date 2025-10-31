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

ls -lh $BACKUP_DIR/postgres/base-$RESTORE_DATE/
ls -lh $BACKUP_DIR/contentstore/contentstore-$RESTORE_DATE/
ls -lh $BACKUP_DIR/pg_wal/
```

Confirm that `base.tar.gz` exists and the contentstore directory contains data before proceeding.

---

## PostgreSQL Restore

### Method 1: Base Backup Restore (Most Common)

1. **Stop Alfresco and PostgreSQL**

   ```bash
   cd /opt/eisenvault_installations/alfresco-home
   ./alfresco.sh stop
   ./alfresco.sh stop postgres
   pgrep -f "java.*alfresco" || echo "Alfresco stopped"
   pgrep -f "postgres" || echo "PostgreSQL stopped"
   ```

2. **Backup Current Database**

   ```bash
   ALF_BASE_DIR=/opt/eisenvault_installations/alfresco-home
   sudo mv $ALF_BASE_DIR/alf_data/postgresql/data \
        $ALF_BASE_DIR/alf_data/postgresql/data.backup.$(date +%Y%m%d-%H%M%S)
   ```

3. **Extract Backup**

   ```bash
   BACKUP_DIR=/mnt/backups/alfresco
   RESTORE_DATE=2025-10-21_14-31-23
   ALF_BASE_DIR=/opt/eisenvault_installations/alfresco-home
   DATA_DIR=$ALF_BASE_DIR/alf_data/postgresql/data

   sudo mkdir -p $DATA_DIR
   cd $BACKUP_DIR/postgres/base-$RESTORE_DATE/
   sudo tar -xzf base.tar.gz -C $DATA_DIR
   sudo chown -R evadm:evadm $DATA_DIR
   sudo chmod 700 $DATA_DIR
   ```

4. **Optional: Configure PITR** (see [Point-in-Time Recovery](#point-in-time-recovery-pitr)).

5. **Start PostgreSQL**

   ```bash
   cd $ALF_BASE_DIR
   ./alfresco.sh start postgres
   tail -f $ALF_BASE_DIR/alf_data/postgresql/postgresql.log
   ```

6. **Verify Connectivity**

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
2. Backup existing `alf_data/postgresql/data` and `alf_data/contentstore` directories.
3. Restore PostgreSQL (Base Backup Restore steps 3–5).
4. Restore contentstore (steps above).
5. Start Alfresco and monitor `tomcat/logs/catalina.out`.

A sample automation script is included in the original documentation (`restore_full.sh`); adapt it for your environment if desired.

---

## Point-in-Time Recovery (PITR)

PITR lets you recover to any moment between a base backup and the current time using WAL archives.

1. **Select Target Time**

   ```bash
   RECOVERY_TIME="2025-10-21 14:30:00"
   ls -lht /mnt/backups/alfresco/pg_wal/
   ```

2. **Restore Base Backup** (steps 1–3 from PostgreSQL Restore).

3. **Create `recovery.conf`** inside the new data directory:

   ```bash
   cat > /tmp/recovery.conf <<EOF
   restore_command = 'cp /mnt/backups/alfresco/pg_wal/%f %p'
   recovery_target_time = '$RECOVERY_TIME'
   recovery_target_action = 'promote'
   recovery_target_timeline = 'latest'
   EOF

   sudo mv /tmp/recovery.conf $DATA_DIR/recovery.conf
   sudo chown evadm:evadm $DATA_DIR/recovery.conf
   sudo chmod 600 $DATA_DIR/recovery.conf
   ```

4. **Start PostgreSQL in Recovery Mode**

   ```bash
   ./alfresco.sh start postgres
   tail -f $ALF_BASE_DIR/alf_data/postgresql/postgresql.log
   ```

5. **Restore Contentstore Snapshot** from the same or earlier timestamp.

6. **Start Alfresco** and validate the application state.

Alternative targets (`recovery_target_xid`, `recovery_target_name`, `recovery_target='immediate'`) can be used when time-based recovery is not suitable.

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

### WAL Files Missing During PITR

```bash
ls -lh /mnt/backups/alfresco/pg_wal/
cat $DATA_DIR/recovery.conf
cp /mnt/backups/alfresco/pg_wal/000000010000000000000001 /tmp/test.wal
sudo chmod 755 /mnt/backups/alfresco/pg_wal
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

```bash
sudo tar -xzf base.tar.gz PG_VERSION -O
psql -h localhost -U alfresco -c "SELECT version();"
```

If versions differ, consider `pg_upgrade`, `pg_dump/pg_restore`, or installing a matching server version.

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
