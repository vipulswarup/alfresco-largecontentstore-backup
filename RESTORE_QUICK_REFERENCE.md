# Restore Quick Reference Card

Quick command reference for common Alfresco restore scenarios. For detailed procedures, see [RESTORE.md](RESTORE.md).

---

## Prerequisites

```bash
# Set your environment variables first
BACKUP_DIR=/mnt/backups/alfresco
ALF_BASE_DIR=/opt/eisenvault_installations/alfresco-home
ALFRESCO_USER=evadm
RESTORE_DATE=2025-10-21_14-31-23  # Change to your backup timestamp
```

---

## Scenario 1: Full System Restore

**When:** Complete disaster recovery or migration to new server

```bash
# 1. Stop Alfresco
cd $ALF_BASE_DIR && ./alfresco.sh stop

# 2. Backup current data (safety)
sudo mv $ALF_BASE_DIR/alf_data/postgresql/data{,.backup.$(date +%Y%m%d-%H%M%S)}
sudo mv $ALF_BASE_DIR/alf_data/contentstore{,.backup.$(date +%Y%m%d-%H%M%S)}

# 3. Restore PostgreSQL
sudo mkdir -p $ALF_BASE_DIR/alf_data/postgresql/data
sudo tar -xzf $BACKUP_DIR/postgres/base-$RESTORE_DATE/base.tar.gz \
    -C $ALF_BASE_DIR/alf_data/postgresql/data
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $ALF_BASE_DIR/alf_data/postgresql/data
sudo chmod 700 $ALF_BASE_DIR/alf_data/postgresql/data

# 4. Restore Contentstore
sudo mkdir -p $ALF_BASE_DIR/alf_data/contentstore
sudo rsync -av --delete \
    $BACKUP_DIR/contentstore/contentstore-$RESTORE_DATE/ \
    $ALF_BASE_DIR/alf_data/contentstore/
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $ALF_BASE_DIR/alf_data/contentstore

# 5. Start Alfresco
cd $ALF_BASE_DIR && ./alfresco.sh start

# 6. Verify
tail -f $ALF_BASE_DIR/tomcat/logs/catalina.out
```

---

## Scenario 2: Database Only Restore

**When:** Database corruption, accidental data deletion, need to rollback database changes

```bash
# 1. Stop Alfresco
cd $ALF_BASE_DIR && ./alfresco.sh stop

# 2. Backup current database (safety)
sudo mv $ALF_BASE_DIR/alf_data/postgresql/data{,.backup.$(date +%Y%m%d-%H%M%S)}

# 3. Restore database
sudo mkdir -p $ALF_BASE_DIR/alf_data/postgresql/data
sudo tar -xzf $BACKUP_DIR/postgres/base-$RESTORE_DATE/base.tar.gz \
    -C $ALF_BASE_DIR/alf_data/postgresql/data
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $ALF_BASE_DIR/alf_data/postgresql/data
sudo chmod 700 $ALF_BASE_DIR/alf_data/postgresql/data

# 4. Start Alfresco
cd $ALF_BASE_DIR && ./alfresco.sh start

# 5. Verify database
psql -h localhost -U alfresco -d alfresco -c "SELECT COUNT(*) FROM alf_node;"
```

---

## Scenario 3: Contentstore Only Restore

**When:** Files corrupted, filesystem issues, need to restore documents

```bash
# 1. Stop Alfresco
cd $ALF_BASE_DIR && ./alfresco.sh stop

# 2. Backup current contentstore (safety)
sudo mv $ALF_BASE_DIR/alf_data/contentstore{,.backup.$(date +%Y%m%d-%H%M%S)}

# 3. Restore contentstore
sudo mkdir -p $ALF_BASE_DIR/alf_data/contentstore
sudo rsync -av --delete \
    $BACKUP_DIR/contentstore/contentstore-$RESTORE_DATE/ \
    $ALF_BASE_DIR/alf_data/contentstore/
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $ALF_BASE_DIR/alf_data/contentstore

# 4. Start Alfresco
cd $ALF_BASE_DIR && ./alfresco.sh start

# 5. Verify contentstore
find $ALF_BASE_DIR/alf_data/contentstore -type f | wc -l
```

---

## Scenario 4: Point-in-Time Recovery (PITR)

**When:** Need to restore to a specific moment (e.g., before accidental deletion at 2:35 PM)

```bash
# 1. Stop Alfresco
cd $ALF_BASE_DIR && ./alfresco.sh stop

# 2. Set recovery time
RECOVERY_TIME="2025-10-21 14:30:00"  # Change to desired time

# 3. Restore base backup (choose backup BEFORE the incident)
sudo mv $ALF_BASE_DIR/alf_data/postgresql/data{,.backup.$(date +%Y%m%d-%H%M%S)}
sudo mkdir -p $ALF_BASE_DIR/alf_data/postgresql/data
sudo tar -xzf $BACKUP_DIR/postgres/base-$RESTORE_DATE/base.tar.gz \
    -C $ALF_BASE_DIR/alf_data/postgresql/data

# 4. Create recovery configuration
cat > /tmp/recovery.conf << EOF
restore_command = 'cp $BACKUP_DIR/pg_wal/%f %p'
recovery_target_time = '$RECOVERY_TIME'
recovery_target_action = 'promote'
recovery_target_timeline = 'latest'
EOF
sudo mv /tmp/recovery.conf $ALF_BASE_DIR/alf_data/postgresql/data/recovery.conf
sudo chown $ALFRESCO_USER:$ALFRESCO_USER $ALF_BASE_DIR/alf_data/postgresql/data/recovery.conf
sudo chmod 600 $ALF_BASE_DIR/alf_data/postgresql/data/recovery.conf

# 5. Fix permissions
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $ALF_BASE_DIR/alf_data/postgresql/data
sudo chmod 700 $ALF_BASE_DIR/alf_data/postgresql/data

# 6. Start PostgreSQL and monitor recovery
cd $ALF_BASE_DIR && ./alfresco.sh start postgres
tail -f $ALF_BASE_DIR/alf_data/postgresql/postgresql.log
# Wait for: "database system is ready to accept connections"

# 7. Restore matching contentstore (from backup BEFORE recovery time)
sudo mv $ALF_BASE_DIR/alf_data/contentstore{,.backup.$(date +%Y%m%d-%H%M%S)}
sudo rsync -av --delete \
    $BACKUP_DIR/contentstore/contentstore-$RESTORE_DATE/ \
    $ALF_BASE_DIR/alf_data/contentstore/
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $ALF_BASE_DIR/alf_data/contentstore

# 8. Start Alfresco
cd $ALF_BASE_DIR && ./alfresco.sh start

# 9. Verify recovery point
psql -h localhost -U alfresco -d alfresco -c "SELECT pg_last_xact_replay_timestamp();"
```

---

## Scenario 5: Restore Single File/Directory from Contentstore

**When:** Need to recover specific document(s) without full restore

```bash
# 1. Don't stop Alfresco (if just recovering files)

# 2. Find the file path in database
psql -h localhost -U alfresco -d alfresco -c "
SELECT content_url 
FROM alf_content_data 
WHERE content_url LIKE '%filename%' 
LIMIT 5;
"
# Example output: store://2025/10/21/14/30/abc123-def456.bin

# 3. Extract path from content_url (e.g., 2025/10/21/14/30/abc123-def456.bin)
FILE_PATH="2025/10/21/14/30/abc123-def456.bin"

# 4. Restore specific file
sudo rsync -av \
    $BACKUP_DIR/contentstore/contentstore-$RESTORE_DATE/$FILE_PATH \
    $ALF_BASE_DIR/alf_data/contentstore/$FILE_PATH
sudo chown $ALFRESCO_USER:$ALFRESCO_USER \
    $ALF_BASE_DIR/alf_data/contentstore/$FILE_PATH

# 5. No restart needed for single files
```

---

## Common Verification Commands

```bash
# Check PostgreSQL is running
pgrep -f postgres

# Check Alfresco/Tomcat is running
pgrep -f "java.*alfresco"

# Check database connectivity
psql -h localhost -U alfresco -d alfresco -c "SELECT 1;"

# Check node count in database
psql -h localhost -U alfresco -d alfresco -c "SELECT COUNT(*) FROM alf_node;"

# Check database size
psql -h localhost -U alfresco -d alfresco -c "SELECT pg_size_pretty(pg_database_size('alfresco'));"

# Check contentstore file count
find $ALF_BASE_DIR/alf_data/contentstore -type f | wc -l

# Check contentstore size
du -sh $ALF_BASE_DIR/alf_data/contentstore

# Check Alfresco logs for errors
tail -100 $ALF_BASE_DIR/tomcat/logs/catalina.out | grep -i error

# Check PostgreSQL logs
tail -100 $ALF_BASE_DIR/alf_data/postgresql/postgresql.log
```

---

## List Available Backups

```bash
# List PostgreSQL backups with sizes
echo "PostgreSQL Backups:"
for dir in $BACKUP_DIR/postgres/base-*; do
    if [ -d "$dir" ]; then
        size=$(du -sh "$dir" | cut -f1)
        date=$(basename "$dir" | sed 's/base-//')
        echo "  $date - Size: $size"
    fi
done

# List contentstore backups with sizes
echo -e "\nContentstore Backups:"
for dir in $BACKUP_DIR/contentstore/contentstore-*; do
    if [ -d "$dir" ]; then
        size=$(du -sh "$dir" | cut -f1)
        date=$(basename "$dir" | sed 's/contentstore-//')
        echo "  $date - Size: $size"
    fi
done

# List WAL files
echo -e "\nWAL Files:"
ls -lh $BACKUP_DIR/pg_wal/ | tail -10
```

---

## Emergency Rollback

If restore goes wrong and you need to rollback to pre-restore state:

```bash
# 1. Stop Alfresco
cd $ALF_BASE_DIR && ./alfresco.sh stop

# 2. Find backup timestamp (from Step 2 of restore)
BACKUP_TIMESTAMP=$(ls -1dt $ALF_BASE_DIR/alf_data/postgresql/data.backup.* | head -1 | sed 's/.*backup\.//')

# 3. Restore from safety backup
sudo rm -rf $ALF_BASE_DIR/alf_data/postgresql/data
sudo mv $ALF_BASE_DIR/alf_data/postgresql/data.backup.$BACKUP_TIMESTAMP \
        $ALF_BASE_DIR/alf_data/postgresql/data

sudo rm -rf $ALF_BASE_DIR/alf_data/contentstore
sudo mv $ALF_BASE_DIR/alf_data/contentstore.backup.$BACKUP_TIMESTAMP \
        $ALF_BASE_DIR/alf_data/contentstore

# 4. Start Alfresco
cd $ALF_BASE_DIR && ./alfresco.sh start
```

---

## Troubleshooting Quick Fixes

### PostgreSQL won't start

```bash
# Fix permissions
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $ALF_BASE_DIR/alf_data/postgresql/data
sudo chmod 700 $ALF_BASE_DIR/alf_data/postgresql/data

# Remove stale PID file
sudo rm -f $ALF_BASE_DIR/alf_data/postgresql/data/postmaster.pid

# Check logs
tail -100 $ALF_BASE_DIR/alf_data/postgresql/postgresql.log
```

### Alfresco won't start

```bash
# Clear caches
rm -rf $ALF_BASE_DIR/tomcat/temp/*
rm -rf $ALF_BASE_DIR/tomcat/work/*

# Check logs
tail -100 $ALF_BASE_DIR/tomcat/logs/catalina.out
```

### Content files missing

```bash
# Verify contentstore exists
ls -la $ALF_BASE_DIR/alf_data/contentstore/

# Check ownership
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $ALF_BASE_DIR/alf_data/contentstore
```

---

## Pre-Restore Checklist

- [ ] Backup timestamp identified: `______________`
- [ ] Current system backed up (safety)
- [ ] Sufficient disk space confirmed (`df -h`)
- [ ] Alfresco stopped
- [ ] Stakeholders notified of downtime
- [ ] Recovery time objective (RTO) understood: `____` hours
- [ ] Rollback plan ready
- [ ] Verification steps prepared

---

## Post-Restore Checklist

- [ ] PostgreSQL started successfully
- [ ] Alfresco/Tomcat started successfully
- [ ] Database accessible (`psql` connection works)
- [ ] Node count verified
- [ ] Contentstore files present
- [ ] Web interface accessible
- [ ] Login works
- [ ] Document preview works
- [ ] Search functionality works
- [ ] No errors in logs
- [ ] Stakeholders notified of completion

---

**For detailed procedures and troubleshooting, always refer to [RESTORE.md](RESTORE.md)**

