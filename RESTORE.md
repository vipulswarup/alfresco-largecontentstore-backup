# Alfresco Restore Procedures

This document provides detailed instructions for restoring Alfresco from backups created by this backup system.

**Looking for quick commands?** See [RESTORE_QUICK_REFERENCE.md](RESTORE_QUICK_REFERENCE.md) for a condensed command reference.

## Table of Contents

1. [Before You Begin](#before-you-begin)
2. [PostgreSQL Restore](#postgresql-restore)
3. [Contentstore Restore](#contentstore-restore)
4. [Full System Restore](#full-system-restore)
5. [Point-in-Time Recovery (PITR)](#point-in-time-recovery-pitr)
6. [Verification](#verification)
7. [Troubleshooting](#troubleshooting)

---

## Before You Begin

### Prerequisites

- Root or sudo access to the Alfresco server
- Alfresco service must be stopped during restore
- Sufficient disk space for restoration
- Access to backup files in `BACKUP_DIR`

### Important Safety Notes

1. **ALWAYS test restores on a non-production system first**
2. **Take a snapshot/backup of the current system before restoring** (in case restore fails)
3. **Document your current configuration** (database names, users, paths)
4. **Verify backup integrity** before starting restore
5. **Plan for downtime** - full restore can take several hours

### Check Backup Integrity

Before starting any restore, verify your backups:

```bash
# Check PostgreSQL backup exists and has content
BACKUP_DIR=/mnt/backups/alfresco
RESTORE_DATE=2025-10-21_14-31-23  # Use actual timestamp from backup

ls -lh $BACKUP_DIR/postgres/base-$RESTORE_DATE/
# Should show base.tar.gz with size > 0

# Verify contentstore backup
ls -lh $BACKUP_DIR/contentstore/contentstore-$RESTORE_DATE/
# Should show directory structure with files

# Check WAL files
ls -lh $BACKUP_DIR/pg_wal/
# Should show WAL segment files
```

---

## PostgreSQL Restore

### Method 1: Full Base Backup Restore (Most Common)

This restores PostgreSQL to the exact state when the base backup was taken.

#### Step 1: Stop Alfresco

```bash
# As the Alfresco user (e.g., evadm)
cd /opt/eisenvault_installations/alfresco-home
./alfresco.sh stop

# Verify Alfresco is stopped
pgrep -f "java.*alfresco" || echo "Alfresco stopped"
```

#### Step 2: Stop PostgreSQL

```bash
# For Alfresco embedded PostgreSQL
cd /opt/eisenvault_installations/alfresco-home
./alfresco.sh stop postgres

# Verify PostgreSQL is stopped
pgrep -f "postgres" || echo "PostgreSQL stopped"
```

#### Step 3: Backup Current Database (Safety)

```bash
# Move current database to a backup location
ALF_BASE_DIR=/opt/eisenvault_installations/alfresco-home
sudo mv $ALF_BASE_DIR/alf_data/postgresql/data \
     $ALF_BASE_DIR/alf_data/postgresql/data.backup.$(date +%Y%m%d-%H%M%S)
```

#### Step 4: Extract PostgreSQL Backup

```bash
# Set variables
BACKUP_DIR=/mnt/backups/alfresco
RESTORE_DATE=2025-10-21_14-31-23  # Replace with your backup timestamp
ALF_BASE_DIR=/opt/eisenvault_installations/alfresco-home
DATA_DIR=$ALF_BASE_DIR/alf_data/postgresql/data

# Create new data directory
sudo mkdir -p $DATA_DIR

# Extract the backup
cd $BACKUP_DIR/postgres/base-$RESTORE_DATE/
sudo tar -xzf base.tar.gz -C $DATA_DIR

# Set proper ownership
ALFRESCO_USER=evadm  # Replace with your Alfresco user
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $DATA_DIR
sudo chmod 700 $DATA_DIR
```

#### Step 5: Configure Recovery (Optional - for PITR)

If you want to apply WAL files for point-in-time recovery:

```bash
# Create recovery.conf in the data directory
cat > /tmp/recovery.conf << EOF
restore_command = 'cp $BACKUP_DIR/pg_wal/%f %p'
recovery_target_timeline = 'latest'
EOF

sudo mv /tmp/recovery.conf $DATA_DIR/recovery.conf
sudo chown $ALFRESCO_USER:$ALFRESCO_USER $DATA_DIR/recovery.conf
sudo chmod 600 $DATA_DIR/recovery.conf
```

For point-in-time recovery to a specific time:
```bash
# Add this line to recovery.conf
recovery_target_time = '2025-10-21 14:30:00'
```

#### Step 6: Start PostgreSQL

```bash
# Start PostgreSQL
cd $ALF_BASE_DIR
./alfresco.sh start postgres

# Wait for PostgreSQL to start (check logs)
tail -f $ALF_BASE_DIR/alf_data/postgresql/postgresql.log

# Look for "database system is ready to accept connections"
```

#### Step 7: Verify Database

```bash
# Connect to database
psql -h localhost -U alfresco -d alfresco

# Check some basic data
\dt  -- List tables
SELECT COUNT(*) FROM alf_node;  -- Should show your node count
\q
```

#### Step 8: Start Alfresco

```bash
cd $ALF_BASE_DIR
./alfresco.sh start

# Monitor startup
tail -f $ALF_BASE_DIR/tomcat/logs/catalina.out
```

---

## Contentstore Restore

### Full Contentstore Restore

#### Step 1: Stop Alfresco

```bash
cd /opt/eisenvault_installations/alfresco-home
./alfresco.sh stop

# Verify stopped
pgrep -f "java.*alfresco" || echo "Alfresco stopped"
```

#### Step 2: Backup Current Contentstore (Safety)

```bash
ALF_BASE_DIR=/opt/eisenvault_installations/alfresco-home
CONTENTSTORE_DIR=$ALF_BASE_DIR/alf_data/contentstore

# Move current contentstore to backup location
sudo mv $CONTENTSTORE_DIR \
     ${CONTENTSTORE_DIR}.backup.$(date +%Y%m%d-%H%M%S)
```

#### Step 3: Restore Contentstore

```bash
# Set variables
BACKUP_DIR=/mnt/backups/alfresco
RESTORE_DATE=2025-10-21_14-31-23  # Replace with your backup timestamp
ALF_BASE_DIR=/opt/eisenvault_installations/alfresco-home
CONTENTSTORE_DIR=$ALF_BASE_DIR/alf_data/contentstore

# Create contentstore directory
sudo mkdir -p $CONTENTSTORE_DIR

# Restore using rsync (preserves permissions and attributes)
sudo rsync -av --delete \
    $BACKUP_DIR/contentstore/contentstore-$RESTORE_DATE/ \
    $CONTENTSTORE_DIR/

# Set proper ownership
ALFRESCO_USER=evadm  # Replace with your Alfresco user
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $CONTENTSTORE_DIR
```

#### Step 4: Verify Contentstore

```bash
# Check directory structure
ls -lh $CONTENTSTORE_DIR/
# Should show year/month/day hierarchy

# Check file count
find $CONTENTSTORE_DIR -type f | wc -l
# Should match expected number of content files
```

#### Step 5: Start Alfresco

```bash
cd $ALF_BASE_DIR
./alfresco.sh start

# Monitor startup
tail -f $ALF_BASE_DIR/tomcat/logs/catalina.out
```

---

## Full System Restore

This performs a complete restore of both database and contentstore to a consistent state.

### Important: Use Matching Timestamps

For a consistent restore, use PostgreSQL and contentstore backups from the same backup run (same or very close timestamps).

```bash
# List available backups
BACKUP_DIR=/mnt/backups/alfresco

echo "PostgreSQL backups:"
ls -1 $BACKUP_DIR/postgres/

echo -e "\nContentstore backups:"
ls -1 $BACKUP_DIR/contentstore/

# Choose matching timestamps (e.g., both from 2025-10-21_14-31-23)
```

### Full Restore Procedure

```bash
#!/bin/bash
# Full Alfresco Restore Script
# Run as root or with sudo

set -e  # Exit on error

# Configuration
BACKUP_DIR=/mnt/backups/alfresco
RESTORE_DATE=2025-10-21_14-31-23  # CHANGE THIS
ALF_BASE_DIR=/opt/eisenvault_installations/alfresco-home
ALFRESCO_USER=evadm  # CHANGE THIS

echo "Starting full Alfresco restore..."
echo "Restore point: $RESTORE_DATE"
echo ""

# 1. Stop Alfresco
echo "Step 1: Stopping Alfresco..."
cd $ALF_BASE_DIR
sudo -u $ALFRESCO_USER ./alfresco.sh stop
sleep 10

# 2. Backup current data
echo "Step 2: Backing up current data..."
BACKUP_SUFFIX=$(date +%Y%m%d-%H%M%S)
sudo mv $ALF_BASE_DIR/alf_data/postgresql/data \
     $ALF_BASE_DIR/alf_data/postgresql/data.backup.$BACKUP_SUFFIX
sudo mv $ALF_BASE_DIR/alf_data/contentstore \
     $ALF_BASE_DIR/alf_data/contentstore.backup.$BACKUP_SUFFIX

# 3. Restore PostgreSQL
echo "Step 3: Restoring PostgreSQL..."
DATA_DIR=$ALF_BASE_DIR/alf_data/postgresql/data
sudo mkdir -p $DATA_DIR
cd $BACKUP_DIR/postgres/base-$RESTORE_DATE/
sudo tar -xzf base.tar.gz -C $DATA_DIR
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $DATA_DIR
sudo chmod 700 $DATA_DIR

# 4. Restore Contentstore
echo "Step 4: Restoring Contentstore..."
CONTENTSTORE_DIR=$ALF_BASE_DIR/alf_data/contentstore
sudo mkdir -p $CONTENTSTORE_DIR
sudo rsync -av --delete \
    $BACKUP_DIR/contentstore/contentstore-$RESTORE_DATE/ \
    $CONTENTSTORE_DIR/
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $CONTENTSTORE_DIR

# 5. Start Alfresco
echo "Step 5: Starting Alfresco..."
cd $ALF_BASE_DIR
sudo -u $ALFRESCO_USER ./alfresco.sh start

echo ""
echo "Restore complete!"
echo "Monitor startup: tail -f $ALF_BASE_DIR/tomcat/logs/catalina.out"
echo ""
echo "Safety backups saved as:"
echo "  - $ALF_BASE_DIR/alf_data/postgresql/data.backup.$BACKUP_SUFFIX"
echo "  - $ALF_BASE_DIR/alf_data/contentstore.backup.$BACKUP_SUFFIX"
```

Save this as `restore_full.sh`, make it executable, and run:

```bash
chmod +x restore_full.sh
sudo ./restore_full.sh
```

---

## Point-in-Time Recovery (PITR)

PITR allows you to restore to any point in time between a base backup and the present, using WAL files.

### When to Use PITR

- Recovering from accidental data deletion
- Rolling back to before a bad configuration change
- Investigating data at a specific point in time

### PITR Procedure

#### Step 1: Choose Recovery Target

Determine the point in time you want to restore to:

```bash
# List WAL files to see timeline
ls -lht /mnt/backups/alfresco/pg_wal/

# Choose a specific timestamp
RECOVERY_TIME="2025-10-21 14:45:00"
```

#### Step 2: Restore Base Backup

Follow steps 1-4 from "PostgreSQL Restore" above.

#### Step 3: Create recovery.conf

```bash
ALF_BASE_DIR=/opt/eisenvault_installations/alfresco-home
DATA_DIR=$ALF_BASE_DIR/alf_data/postgresql/data
BACKUP_DIR=/mnt/backups/alfresco

cat > /tmp/recovery.conf << EOF
# Restore command to fetch WAL files
restore_command = 'cp $BACKUP_DIR/pg_wal/%f %p'

# Recovery target time
recovery_target_time = '$RECOVERY_TIME'

# Stop at recovery target
recovery_target_action = 'promote'

# Use latest timeline
recovery_target_timeline = 'latest'
EOF

sudo mv /tmp/recovery.conf $DATA_DIR/recovery.conf
sudo chown $ALFRESCO_USER:$ALFRESCO_USER $DATA_DIR/recovery.conf
sudo chmod 600 $DATA_DIR/recovery.conf
```

#### Step 4: Start PostgreSQL

```bash
cd $ALF_BASE_DIR
./alfresco.sh start postgres

# Monitor recovery in logs
tail -f $ALF_BASE_DIR/alf_data/postgresql/postgresql.log

# Look for:
# "starting point-in-time recovery to ..."
# "recovery stopping before commit of transaction ..."
# "database system is ready to accept connections"
```

#### Step 5: Verify Recovery

```bash
# Connect and check data
psql -h localhost -U alfresco -d alfresco

# Check timestamp of last transaction
SELECT pg_last_xact_replay_timestamp();

\q
```

#### Step 6: Restore Contentstore

Use a contentstore backup taken BEFORE your recovery target time.

#### Step 7: Start Alfresco

```bash
cd $ALF_BASE_DIR
./alfresco.sh start
```

### PITR Alternative Target Options

Instead of `recovery_target_time`, you can use:

```conf
# Stop at specific transaction ID
recovery_target_xid = '12345678'

# Stop when specific restore point is reached
recovery_target_name = 'before_delete_operation'

# Recover to end of WAL (latest possible)
recovery_target = 'immediate'
```

---

## Verification

After any restore, perform these verification steps:

### 1. PostgreSQL Health Check

```bash
# Connect to database
psql -h localhost -U alfresco -d alfresco

-- Check database size
SELECT pg_size_pretty(pg_database_size('alfresco'));

-- Check table counts
SELECT COUNT(*) FROM alf_node;
SELECT COUNT(*) FROM alf_node_properties;
SELECT COUNT(*) FROM alf_content_data;

-- Check for errors in system
SELECT * FROM alf_server 
ORDER BY id DESC 
LIMIT 10;

\q
```

### 2. Contentstore Verification

```bash
# Count files
find $ALF_BASE_DIR/alf_data/contentstore -type f | wc -l

# Check permissions
ls -la $ALF_BASE_DIR/alf_data/contentstore/

# Verify structure
ls -R $ALF_BASE_DIR/alf_data/contentstore/ | head -20
```

### 3. Alfresco Application Check

```bash
# Check Alfresco startup logs
tail -100 $ALF_BASE_DIR/tomcat/logs/catalina.out

# Look for:
# - "Server startup in [X] ms" (successful startup)
# - No ERROR messages
# - Repository started successfully
```

### 4. Web Interface Verification

1. Access Alfresco Share: `http://your-server:8080/share`
2. Log in with admin credentials
3. Browse sites and documents
4. Check document preview functionality
5. Verify search functionality
6. Check user profiles and permissions

### 5. Content Integrity Check

```bash
# Run Alfresco's content store integrity checker (if available)
# Or manually verify a few random files

# Get a random content URL from database
psql -h localhost -U alfresco -d alfresco -c "
SELECT content_url 
FROM alf_content_data 
WHERE content_url IS NOT NULL 
LIMIT 5;
"

# Check if corresponding files exist in contentstore
# Format: store://2025/10/21/14/30/abc123-def456.bin
```

---

## Troubleshooting

### PostgreSQL Won't Start After Restore

**Issue:** PostgreSQL fails to start after extracting backup

**Solutions:**

```bash
# Check permissions
ls -la $ALF_BASE_DIR/alf_data/postgresql/data
# Should be owned by Alfresco user with 700 permissions

# Check logs
tail -100 $ALF_BASE_DIR/alf_data/postgresql/postgresql.log

# Common fixes:
# 1. Fix ownership
sudo chown -R evadm:evadm $ALF_BASE_DIR/alf_data/postgresql/data

# 2. Fix permissions
sudo chmod 700 $ALF_BASE_DIR/alf_data/postgresql/data

# 3. Remove old PID file if exists
sudo rm -f $ALF_BASE_DIR/alf_data/postgresql/data/postmaster.pid
```

### WAL Files Not Found During PITR

**Issue:** `restore_command` fails to find WAL files

**Solutions:**

```bash
# 1. Verify WAL files exist
ls -lh $BACKUP_DIR/pg_wal/

# 2. Check restore_command path in recovery.conf
cat $DATA_DIR/recovery.conf

# 3. Test restore command manually
cp $BACKUP_DIR/pg_wal/000000010000000000000001 /tmp/test.wal
# If this fails, check path and permissions

# 4. Ensure WAL directory is readable
sudo chmod 755 $BACKUP_DIR/pg_wal/
```

### Contentstore Files Missing After Restore

**Issue:** Files in database but content missing

**Solutions:**

```bash
# 1. Verify contentstore was restored
ls -la $ALF_BASE_DIR/alf_data/contentstore/

# 2. Check for orphaned content references
# This can happen if database is newer than contentstore

# 3. Restore contentstore from matching backup
# Use contentstore backup with same or earlier timestamp as database

# 4. Run Alfresco's content store cleaner (optional)
# This removes orphaned database references
```

### Alfresco Shows Errors After Restore

**Issue:** Alfresco starts but shows errors or missing content

**Possible Causes:**

1. **Timestamp mismatch**: Database and contentstore from different times
   - Solution: Restore both from the same backup run

2. **Incomplete restore**: Restore was interrupted
   - Solution: Re-run restore from scratch

3. **Configuration mismatch**: Restored database expects different paths
   - Solution: Check `alfresco-global.properties` matches restored environment

4. **Cache issues**: Old cache data conflicting
   - Solution: Clear Alfresco caches:
   ```bash
   rm -rf $ALF_BASE_DIR/tomcat/temp/*
   rm -rf $ALF_BASE_DIR/tomcat/work/*
   ```

### Restore Takes Too Long

**Issue:** Restore process is extremely slow

**Solutions:**

```bash
# 1. For PostgreSQL: Extract to faster storage first
sudo tar -xzf base.tar.gz -C /tmp/fast_storage/
sudo mv /tmp/fast_storage/* $DATA_DIR/

# 2. For Contentstore: Use parallel rsync
sudo rsync -av --delete --progress \
    $BACKUP_DIR/contentstore/contentstore-$RESTORE_DATE/ \
    $CONTENTSTORE_DIR/

# 3. Check disk I/O
iostat -x 5
# If %util is 100%, disk is bottleneck

# 4. Check available space
df -h $ALF_BASE_DIR
```

### Database Version Mismatch

**Issue:** PostgreSQL version in backup doesn't match current installation

**This is rare since we're restoring to the same Alfresco installation, but:**

```bash
# Check PostgreSQL version in backup
sudo tar -xzf base.tar.gz PG_VERSION -O

# Check running PostgreSQL version
psql -h localhost -U alfresco -c "SELECT version();"

# If versions don't match, you may need to:
# 1. Use pg_upgrade (complex)
# 2. Use pg_dump/pg_restore instead of base backup
# 3. Install matching PostgreSQL version
```

---

## Testing Restores

### Regular Restore Testing Schedule

Test your restore procedures regularly (recommended: monthly):

```bash
# 1. Document current state
psql -h localhost -U alfresco -d alfresco -c "
SELECT 
    COUNT(*) as node_count,
    pg_size_pretty(pg_database_size('alfresco')) as db_size
FROM alf_node;
" > /tmp/pre_restore_state.txt

# 2. Perform restore on a test system
# (Never test on production!)

# 3. Verify restored state matches

# 4. Document lessons learned
```

### Restore Test Checklist

- [ ] Backup files are accessible and readable
- [ ] Sufficient disk space available
- [ ] Test system matches production environment
- [ ] Downtime window is adequate
- [ ] Rollback plan is documented
- [ ] All passwords and credentials available
- [ ] Monitoring is in place
- [ ] Stakeholders are notified
- [ ] Restore procedure is documented
- [ ] Verification steps are prepared

---

## Emergency Restore Contacts

Document key contacts for emergency restore scenarios:

```
Database Administrator: _________________
System Administrator: _________________
Alfresco Administrator: _________________
Backup System Owner: _________________
On-call Support: _________________
```

---

## Additional Resources

### PostgreSQL Recovery Documentation
- PostgreSQL 9.4 Recovery: https://www.postgresql.org/docs/9.4/recovery-config.html
- PITR Guide: https://www.postgresql.org/docs/9.4/continuous-archiving.html

### Alfresco Documentation
- Alfresco Backup and Restore: https://docs.alfresco.com/
- Content Store Configuration: https://docs.alfresco.com/

### Related Files
- `README.md`: Backup system setup and configuration
- `backup.py`: Main backup script
- `.env`: Configuration (passwords, paths)
- `/var/log/alfresco-backup/`: Backup logs

---

## Restore Summary Quick Reference

```bash
# Quick Full Restore (modify variables as needed)
BACKUP_DIR=/mnt/backups/alfresco
RESTORE_DATE=2025-10-21_14-31-23
ALF_BASE_DIR=/opt/eisenvault_installations/alfresco-home
ALFRESCO_USER=evadm

# Stop Alfresco
cd $ALF_BASE_DIR && ./alfresco.sh stop

# Restore PostgreSQL
sudo mv $ALF_BASE_DIR/alf_data/postgresql/data{,.backup}
sudo mkdir -p $ALF_BASE_DIR/alf_data/postgresql/data
sudo tar -xzf $BACKUP_DIR/postgres/base-$RESTORE_DATE/base.tar.gz \
    -C $ALF_BASE_DIR/alf_data/postgresql/data
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER \
    $ALF_BASE_DIR/alf_data/postgresql/data

# Restore Contentstore
sudo mv $ALF_BASE_DIR/alf_data/contentstore{,.backup}
sudo rsync -av --delete \
    $BACKUP_DIR/contentstore/contentstore-$RESTORE_DATE/ \
    $ALF_BASE_DIR/alf_data/contentstore/
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER \
    $ALF_BASE_DIR/alf_data/contentstore

# Start Alfresco
cd $ALF_BASE_DIR && ./alfresco.sh start
```

---

**Remember:** Always test restores on a non-production system first. Document every step. Have a rollback plan ready.

